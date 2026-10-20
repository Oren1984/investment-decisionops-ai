<#
.SYNOPSIS
  Checks runner (plan §17.4): lint, types, unit + integration tests, API-contract freshness and security scans.
  Same steps as scripts/check.sh. Every step runs even if an earlier one fails; a summary is printed and the exit
  code is 1 if any step failed. Needs Docker and Node/npm. Backend tooling runs in the test image; Postgres is a
  throwaway container on a private network (no published port, removed at exit).
.EXAMPLE
  pwsh scripts/check.ps1
  pwsh scripts/check.ps1 -SkipSecurity      # offline
  pwsh scripts/check.ps1 -E2E               # also Playwright against the isolated E2E stack (E2E_SETUP_TOKEN set)
#>
param([switch]$E2E, [switch]$SkipSecurity)
$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false) # decode native output (OpenAPI JSON) as UTF-8
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Frontend = Join-Path $Root "frontend"
$TestImage = "decisionops-backend-test"
$PgImage = "pgvector/pgvector:0.8.7-pg18"
$GitleaksImage = "zricethezav/gitleaks:v8.29.1"
$Tag = "check-$PID"
$Tmp = Join-Path ([IO.Path]::GetTempPath()) $Tag
New-Item -ItemType Directory -Force $Tmp | Out-Null
# npm.ps1/npx.ps1 rebuild their arguments from the invocation line, which breaks indirect calls: use the .cmd shims.
$Npm = if ($IsWindows) { "npm.cmd" } else { "npm" }
$Npx = if ($IsWindows) { "npx.cmd" } else { "npx" }
$Results = [Collections.Generic.List[string]]::new()
$Failed = $false

# Reviewed exceptions: see scripts/check.sh and docs/security/dependency-findings.md.
$PipAuditIgnore = "GHSA-84m7-p3x7-pcfv", "PYSEC-2026-311", "PYSEC-2026-3813", "PYSEC-2026-3814", "PYSEC-2026-3815"

function Step([string]$Name, [scriptblock]$Body) {
  Write-Host "`n==> $Name"
  $global:LASTEXITCODE = 0
  $ok = $true
  try { & $Body | Out-Host; if ($LASTEXITCODE -ne 0) { $ok = $false } } catch { Write-Host $_; $ok = $false }
  if ($ok) { $Results.Add("PASS  $Name") } else { $Results.Add("FAIL  $Name"); $script:Failed = $true }
}
function Native { & $args[0] @($args | Select-Object -Skip 1); if ($LASTEXITCODE -ne 0) { throw "$($args[0]) exited $LASTEXITCODE" } }

try {
  Step "build test image" { Native docker build -q -f "$Root\backend\Dockerfile" --target test -t $TestImage $Root | Out-Null }
  Step "ruff" { Native docker run --rm $TestImage python -m ruff check app tests }
  Step "pytest (throwaway Postgres)" {
    Native docker network create $Tag | Out-Null
    Native docker run -d --name "$Tag-db" --network $Tag -e POSTGRES_USER=decisionops -e POSTGRES_PASSWORD=check $PgImage | Out-Null
    $ready = $false
    for ($i = 0; $i -lt 60 -and -not $ready; $i++) {
      & docker exec "$Tag-db" pg_isready -U decisionops -h 127.0.0.1 *> $null
      if ($LASTEXITCODE -eq 0) { $ready = $true } else { Start-Sleep 1 }
    }
    if (-not $ready) { throw "Postgres did not become ready" }
    Native docker run --rm --network $Tag -e "TEST_ADMIN_URL=postgresql://decisionops:check@$Tag-db:5432/postgres" `
      $TestImage python -m pytest -p no:warnings -q tests
  }
  Step "npm dependencies" { if (-not (Test-Path "$Frontend\node_modules")) { Push-Location $Frontend; try { Native $Npm ci --no-audit --no-fund } finally { Pop-Location } } }
  Step "tsc -b" { Push-Location $Frontend; try { Native $Npx tsc -b } finally { Pop-Location } }
  Step "vitest" { Push-Location $Frontend; try { Native $Npx vitest run } finally { Pop-Location } }
  Step "OpenAPI + TS schema fresh" {
    $json = & docker run --rm $TestImage python -m app.cli openapi
    if ($LASTEXITCODE -ne 0) { throw "openapi export failed" }
    [IO.File]::WriteAllText("$Tmp\openapi.json", (($json -join "`n")), [Text.UTF8Encoding]::new($false))
    Push-Location $Frontend
    try { Native $Npx openapi-typescript "$Tmp\openapi.json" -o "$Tmp\schema.d.ts" --default-non-nullable false *> $null } finally { Pop-Location }
    $stale = @()
    # Compare ignoring line endings (the committed files may be checked out with CRLF).
    $norm = { param($p) (Get-Content -Raw $p) -replace "`r`n", "`n" -replace "`n$", "" }
    if ((& $norm "$Tmp\openapi.json") -ne (& $norm "$Frontend\openapi.json")) { $stale += "frontend/openapi.json" }
    if ((& $norm "$Tmp\schema.d.ts") -ne (& $norm "$Frontend\src\api\schema.d.ts")) { $stale += "frontend/src/api/schema.d.ts" }
    if ($stale) { throw "Stale: $($stale -join ', '). Regenerate: python -m app.cli openapi > frontend/openapi.json; cd frontend; npm run gen:api" }
  }
  if (-not $SkipSecurity) {
    Step "gitleaks" {
      # Scan exactly what git would see (tracked + untracked, minus .gitignore), so local .env files are not reported.
      $tree = Join-Path $Tmp "tree"
      Push-Location $Root
      try {
        foreach ($f in (& git ls-files --cached --others --exclude-standard)) {
          if (-not (Test-Path -LiteralPath $f -PathType Leaf)) { continue }
          $dest = Join-Path $tree $f
          New-Item -ItemType Directory -Force (Split-Path $dest) | Out-Null
          Copy-Item -LiteralPath $f $dest
        }
      } finally { Pop-Location }
      Copy-Item "$Root\.gitleaks.toml" "$Tmp\gitleaks.toml"
      Native docker run --rm -v "${Tmp}:/scan" $GitleaksImage dir /scan/tree --config /scan/gitleaks.toml --redact --no-banner
    }
    Step "pip-audit" {
      $ignores = ($PipAuditIgnore | ForEach-Object { "--ignore-vuln $_" }) -join " "
      Native docker run --rm $TestImage sh -c "uv export --frozen --no-dev --extra embeddings --no-hashes --no-emit-project -q > /tmp/req.txt && pip-audit --strict -r /tmp/req.txt --disable-pip --no-deps $ignores"
    }
    Step "npm audit --omit=dev" { Push-Location $Frontend; try { Native $Npm audit --omit=dev } finally { Pop-Location } }
    Step "trivy (HIGH/CRITICAL, fixable)" {
      if (-not (Get-Command trivy -ErrorAction SilentlyContinue)) { throw "trivy not installed" }
      $bad = $false
      foreach ($img in "decisionops-app:local", "decisionops-web:local") {
        & docker image inspect $img *> $null
        if ($LASTEXITCODE -ne 0) { Write-Host "$img not built (docker compose build)"; $bad = $true; continue }
        & trivy image -q --scanners vuln --severity HIGH,CRITICAL --table-mode detailed $img
        & trivy image -q --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --ignorefile "$Root\.trivyignore.yaml" `
          --exit-code 1 --table-mode summary $img *> $null
        if ($LASTEXITCODE -ne 0) { Write-Host "${img}: fixable HIGH/CRITICAL findings"; $bad = $true }
      }
      if ($bad) { throw "trivy findings" }
    }
  }
  if ($E2E) { Step "playwright e2e" { Push-Location $Frontend; try { Native $Npx playwright test } finally { Pop-Location } } }
} finally {
  & docker rm -f "$Tag-db" *> $null
  & docker network rm $Tag *> $null
  Remove-Item -Recurse -Force $Tmp -ErrorAction SilentlyContinue
}

Write-Host "`nSummary:"
$Results | ForEach-Object { Write-Host $_ }
exit ([int]$Failed)
