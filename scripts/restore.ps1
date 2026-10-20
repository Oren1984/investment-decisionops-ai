<#
.SYNOPSIS
  Restore a backup made by scripts/backup.(ps1|sh), then re-apply the erasure ledger BEFORE the app becomes
  available, so a restore can never resurrect erased content. Destructive: replaces both databases and the uploads.
  Order: verify checksums -> confirm -> stop app services -> restore databases -> restore uploads -> migrations ->
         erasure-ledger replay (backup copy + live ledger) -> compare counts -> verify evidence hashes -> start.
.EXAMPLE
  pwsh scripts/restore.ps1 backups\20261019T120000Z
  pwsh scripts/restore.ps1 -Project decisionops-e2e -EnvFile C:\path\e2e.env -Yes C:\path\backups\<ts>
#>
param(
  [Parameter(Mandatory = $true, Position = 0)][string]$BackupDir,
  [string]$Project = "decisionops",
  [string]$EnvFile = (Join-Path $PSScriptRoot "..\.env"),
  [switch]$Yes
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackupDir = (Resolve-Path $BackupDir).Path

function Dc {
  $base = @("compose", "-f", (Join-Path $Root "compose.yaml"), "-p", $Project)
  if (Test-Path $EnvFile) { $base += @("--env-file", $EnvFile) }
  & docker @base @args
  if ($LASTEXITCODE -ne 0) { throw "docker compose $($args -join ' ') failed ($LASTEXITCODE)" }
}
function D { & docker @args; if ($LASTEXITCODE -ne 0) { throw "docker $($args -join ' ') failed ($LASTEXITCODE)" } }

Write-Host "1/8 Verifying checksums in $BackupDir"
foreach ($line in Get-Content (Join-Path $BackupDir "SHA256SUMS") | Where-Object { $_.Trim() }) {
  $hash, $name = $line -split "\s+", 2
  $actual = (Get-FileHash -Algorithm SHA256 (Join-Path $BackupDir $name.Trim())).Hash.ToLower()
  if ($actual -ne $hash.ToLower()) { throw "Checksum mismatch for ${name}: backup is damaged. Nothing was changed." }
}

if (-not $Yes) {
  Write-Host "This REPLACES all data of project '$Project' with the backup $(Split-Path -Leaf $BackupDir)."
  if ((Read-Host "Type the project name to continue") -ne $Project) { Write-Host "Cancelled. Nothing was changed."; exit 1 }
}

Write-Host "2/8 Stopping app services (the database keeps running)"
Dc stop web api api-demo worker
Dc up -d db | Out-Null

Write-Host "3/8 Restoring databases"
foreach ($db in "decisionops", "decisionops_demo") {
  Dc cp (Join-Path $BackupDir "$db.dump") "db:/tmp/$db.dump"
  Dc exec -T db sh -c "dropdb -U postgres --if-exists --force $db && pg_restore -U postgres --create -d postgres /tmp/$db.dump && rm -f /tmp/$db.dump"
}

Write-Host "4/8 Restoring uploads"
$helper = "$Project-restore-helper"
& docker rm -f $helper 2>$null | Out-Null
Dc run -d --no-deps --name $helper --entrypoint sleep api 600 | Out-Null
D cp (Join-Path $BackupDir "uploads.tar.gz") "${helper}:/tmp/uploads.tar.gz"
D cp (Join-Path $BackupDir "erasure-ledger.jsonl") "${helper}:/tmp/backup-ledger.jsonl"
D exec -u 0 $helper sh -c "chown app:app /tmp/uploads.tar.gz /tmp/backup-ledger.jsonl"
D exec $helper sh -c "rm -rf /data/uploads && tar xzf /tmp/uploads.tar.gz -C /data && mkdir -p /data/ledger"
# Live ledger stays authoritative (it may hold erasures newer than the backup); if it is missing, adopt the copy.
D exec $helper sh -c "[ -s /data/ledger/erasure-ledger.jsonl ] || cp /tmp/backup-ledger.jsonl /data/ledger/erasure-ledger.jsonl"

Write-Host "5/8 Applying migrations"
Dc run --rm migrate | Out-Null

Write-Host "6/8 Re-applying the erasure ledger (backup copy, then live ledger)"
D exec $helper python -m app.cli replay-erasure-ledger --path /tmp/backup-ledger.jsonl
D exec $helper python -m app.cli replay-erasure-ledger

Write-Host "7/8 Integrity: row counts vs. the backup manifest, then evidence hashes"
$countsSql = @"
select json_object_agg(t, n) from (
  select 'app_user' t, count(*) n from app_user union all select 'decision', count(*) from decision
  union all select 'evidence_snapshot', count(*) from evidence_snapshot union all select 'evidence_item', count(*) from evidence_item
  union all select 'document', count(*) from document union all select 'chunk', count(*) from chunk
  union all select 'order_ticket', count(*) from order_ticket union all select 'audit_event', count(*) from audit_event
  union all select 'share_grant', count(*) from share_grant union all select 'erasure_ledger', count(*) from erasure_ledger) x
"@ -replace "`r?`n", " "
$manifest = Get-Content (Join-Path $BackupDir "manifest.json") -Raw | ConvertFrom-Json
Write-Host "  backup : $($manifest.counts | ConvertTo-Json -Compress)"
Write-Host "  restore: $((Dc exec -T db psql -U postgres -d decisionops -Atc $countsSql | Out-String).Trim())"
Write-Host "  (documents/chunks may be lower than the backup when the ledger erased content after it was taken)"
& docker exec $helper python -m app.cli verify-evidence
$verified = $LASTEXITCODE -eq 0
& docker rm -f $helper | Out-Null
if (-not $verified) { throw "Evidence verification FAILED; the app was not started." }

Write-Host "8/8 Starting the app"
Dc up -d
Write-Host "Restore complete."
