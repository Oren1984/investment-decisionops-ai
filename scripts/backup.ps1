<#
.SYNOPSIS
  Backup: pg_dump (-Fc) of both databases, the uploads archive, a copy of the erasure ledger, row counts and a
  SHA-256 manifest -> <OutDir>\<UTC timestamp>\, then <OutDir>\last-backup.json (read by the backup-age alert).
  Backups contain personal data: the folder is git-ignored. Retention: BACKUP_RETENTION_DAYS (default 30).
.EXAMPLE
  pwsh scripts/backup.ps1
  pwsh scripts/backup.ps1 -Project decisionops-e2e -EnvFile C:\path\e2e.env -OutDir C:\path\backups
#>
param(
  [string]$Project = "decisionops",
  [string]$EnvFile = (Join-Path $PSScriptRoot "..\.env"),
  [string]$OutDir = (Join-Path $PSScriptRoot "..\backups")
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Retention = if ($env:BACKUP_RETENTION_DAYS) { [int]$env:BACKUP_RETENTION_DAYS } else { 30 }

function Dc {
  $base = @("compose", "-f", (Join-Path $Root "compose.yaml"), "-p", $Project)
  if (Test-Path $EnvFile) { $base += @("--env-file", $EnvFile) }
  & docker @base @args
  if ($LASTEXITCODE -ne 0) { throw "docker compose $($args -join ' ') failed ($LASTEXITCODE)" }
}

$started = (Get-Date).ToUniversalTime()
$ts = $started.ToString("yyyyMMddTHHmmssZ")
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$dir = Join-Path (Resolve-Path $OutDir).Path $ts
New-Item -ItemType Directory -Force -Path $dir | Out-Null
Write-Host "Backing up project '$Project' to $dir"

foreach ($db in "decisionops", "decisionops_demo") {
  Dc exec -T db sh -c "pg_dump -U postgres -Fc -f /tmp/$db.dump $db"
  Dc cp "db:/tmp/$db.dump" (Join-Path $dir "$db.dump")
  Dc exec -T db rm -f "/tmp/$db.dump"
}
Dc exec -T api sh -c "mkdir -p /data/uploads /data/ledger && tar czf /tmp/uploads.tar.gz -C /data uploads && cp /data/ledger/erasure-ledger.jsonl /tmp/ledger.jsonl 2>/dev/null || touch /tmp/ledger.jsonl"
Dc cp api:/tmp/uploads.tar.gz (Join-Path $dir "uploads.tar.gz")
# The erasure ledger is also kept outside the database dump, so a restore can always re-apply erasures.
Dc cp api:/tmp/ledger.jsonl (Join-Path $dir "erasure-ledger.jsonl")
Dc exec -T api rm -f /tmp/uploads.tar.gz /tmp/ledger.jsonl

$countsSql = @"
select json_object_agg(t, n) from (
  select 'app_user' t, count(*) n from app_user union all select 'decision', count(*) from decision
  union all select 'evidence_snapshot', count(*) from evidence_snapshot union all select 'evidence_item', count(*) from evidence_item
  union all select 'document', count(*) from document union all select 'chunk', count(*) from chunk
  union all select 'order_ticket', count(*) from order_ticket union all select 'audit_event', count(*) from audit_event
  union all select 'share_grant', count(*) from share_grant union all select 'erasure_ledger', count(*) from erasure_ledger) x
"@ -replace "`r?`n", " "
$counts = (Dc exec -T db psql -U postgres -d decisionops -Atc $countsSql | Out-String).Trim() | ConvertFrom-Json
$revision = (Dc exec -T db psql -U postgres -d decisionops -Atc "select version_num from alembic_version" | Out-String).Trim()

$names = "decisionops.dump", "decisionops_demo.dump", "uploads.tar.gz", "erasure-ledger.jsonl"
$files = foreach ($n in $names) { [ordered]@{ name = $n; sha256 = (Get-FileHash -Algorithm SHA256 (Join-Path $dir $n)).Hash.ToLower() } }
# Same format as sha256sum, so either script can verify either backup.
# LF line endings only: sha256sum treats a trailing CR as part of the file name.
(($files | ForEach-Object { "$($_.sha256)  $($_.name)" }) -join "`n") + "`n" |
  Set-Content -NoNewline -Encoding ascii (Join-Path $dir "SHA256SUMS")
$completed = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
[ordered]@{ format = 1; project = $Project; started_at = $started.ToString("yyyy-MM-ddTHH:mm:ssZ"); completed_at = $completed
  alembic_revision = $revision; counts = $counts; files = @($files); retention_days = $Retention } |
  ConvertTo-Json -Depth 5 -Compress | Set-Content -Encoding utf8NoBOM (Join-Path $dir "manifest.json")
[ordered]@{ completed_at = $completed; path = $ts; project = $Project; counts = $counts } |
  ConvertTo-Json -Depth 5 -Compress | Set-Content -Encoding utf8NoBOM (Join-Path $OutDir "last-backup.json")

# Retention: remove timestamped backup folders older than the window (never anything else).
Get-ChildItem -Directory $OutDir | Where-Object { $_.Name -match '^20\d{6}T\d{6}Z$' -and $_.LastWriteTime -lt (Get-Date).AddDays(-$Retention) } |
  Remove-Item -Recurse -Force

Write-Host "Backup complete: $dir"
Write-Host "  counts: $($counts | ConvertTo-Json -Compress)"
