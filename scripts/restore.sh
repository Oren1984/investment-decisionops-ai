#!/usr/bin/env sh
# Restore a backup made by scripts/backup.sh, then re-apply the erasure ledger BEFORE the app becomes available,
# so a restore can never resurrect erased content. Destructive: replaces both databases and the uploads.
#
# Order: verify checksums -> confirm -> stop app services -> restore databases -> restore uploads -> migrations ->
#        erasure-ledger replay (backup copy + live ledger) -> compare counts -> verify evidence hashes -> start.
#
# Usage: scripts/restore.sh [-p compose_project] [-e env_file] [-y] <backup_dir>
#   -y  skip the typed confirmation (for scripted tests on an isolated project only)
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PROJECT=decisionops
ENV_FILE="$ROOT/.env"
YES=0
while getopts "p:e:y" opt; do
  case $opt in
    p) PROJECT=$OPTARG ;;
    e) ENV_FILE=$OPTARG ;;
    y) YES=1 ;;
    *) echo "usage: $0 [-p project] [-e env_file] [-y] <backup_dir>" >&2; exit 2 ;;
  esac
done
shift $((OPTIND - 1))
BACKUP=${1:?usage: $0 [-p project] [-e env_file] [-y] <backup_dir>}
BACKUP=$(cd "$BACKUP" && pwd)
export MSYS_NO_PATHCONV=1 # Git Bash on Windows: keep container paths as written...
if command -v cygpath >/dev/null 2>&1; then # ...so host paths must be given to docker in Windows form
  ROOT=$(cygpath -m "$ROOT"); ENV_FILE=$(cygpath -m "$ENV_FILE"); BACKUP=$(cygpath -m "$BACKUP")
fi

dc() {
  if [ -f "$ENV_FILE" ]; then docker compose -f "$ROOT/compose.yaml" -p "$PROJECT" --env-file "$ENV_FILE" "$@"
  else docker compose -f "$ROOT/compose.yaml" -p "$PROJECT" "$@"; fi
}

echo "1/8 Verifying checksums in $BACKUP"
(cd "$BACKUP" && sha256sum -c --quiet SHA256SUMS) || { echo "Checksum mismatch: backup is damaged. Nothing was changed." >&2; exit 1; }

if [ "$YES" -ne 1 ]; then
  echo "This REPLACES all data of project '$PROJECT' with the backup $(basename "$BACKUP")."
  printf "Type the project name to continue: "
  read -r answer
  [ "$answer" = "$PROJECT" ] || { echo "Cancelled. Nothing was changed."; exit 1; }
fi

echo "2/8 Stopping app services (the database keeps running)"
dc stop web api api-demo worker
dc up -d db >/dev/null

echo "3/8 Restoring databases"
for db in decisionops decisionops_demo; do
  dc cp "$BACKUP/$db.dump" "db:/tmp/$db.dump"
  dc exec -T db sh -c "dropdb -U postgres --if-exists --force $db && pg_restore -U postgres --create -d postgres /tmp/$db.dump && rm -f /tmp/$db.dump"
done

echo "4/8 Restoring uploads"
HELPER="${PROJECT}-restore-helper"
docker rm -f "$HELPER" >/dev/null 2>&1 || true
dc run -d --no-deps --name "$HELPER" --entrypoint sleep api 600 >/dev/null
docker cp "$BACKUP/uploads.tar.gz" "$HELPER:/tmp/uploads.tar.gz"
docker cp "$BACKUP/erasure-ledger.jsonl" "$HELPER:/tmp/backup-ledger.jsonl"
docker exec -u 0 "$HELPER" sh -c 'chown app:app /tmp/uploads.tar.gz /tmp/backup-ledger.jsonl'
docker exec "$HELPER" sh -c 'rm -rf /data/uploads && tar xzf /tmp/uploads.tar.gz -C /data && mkdir -p /data/ledger'
# Live ledger stays authoritative (it may hold erasures newer than the backup); if it is missing, adopt the copy.
docker exec "$HELPER" sh -c '[ -s /data/ledger/erasure-ledger.jsonl ] || cp /tmp/backup-ledger.jsonl /data/ledger/erasure-ledger.jsonl'

echo "5/8 Applying migrations"
dc run --rm migrate >/dev/null

echo "6/8 Re-applying the erasure ledger (backup copy, then live ledger)"
docker exec "$HELPER" python -m app.cli replay-erasure-ledger --path /tmp/backup-ledger.jsonl
docker exec "$HELPER" python -m app.cli replay-erasure-ledger

echo "7/8 Integrity: row counts vs. the backup manifest, then evidence hashes"
COUNTS_SQL="select json_object_agg(t, n) from (
  select 'app_user' t, count(*) n from app_user union all select 'decision', count(*) from decision
  union all select 'evidence_snapshot', count(*) from evidence_snapshot union all select 'evidence_item', count(*) from evidence_item
  union all select 'document', count(*) from document union all select 'chunk', count(*) from chunk
  union all select 'order_ticket', count(*) from order_ticket union all select 'audit_event', count(*) from audit_event
  union all select 'share_grant', count(*) from share_grant union all select 'erasure_ledger', count(*) from erasure_ledger) x"
echo "  backup : $(sed -n 's/.*"counts": \({[^}]*}\).*/\1/p' "$BACKUP/manifest.json" | head -1)"
echo "  restore: $(dc exec -T db psql -U postgres -d decisionops -Atc "$COUNTS_SQL" | tr -d '\r')"
echo "  (documents/chunks may be lower than the backup when the ledger erased content after it was taken)"
docker exec "$HELPER" python -m app.cli verify-evidence || { echo "Evidence verification FAILED; the app was not started." >&2; docker rm -f "$HELPER" >/dev/null; exit 1; }
docker rm -f "$HELPER" >/dev/null

echo "8/8 Starting the app"
dc up -d
echo "Restore complete."
