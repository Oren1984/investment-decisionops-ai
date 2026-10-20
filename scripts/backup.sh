#!/usr/bin/env sh
# Backup: pg_dump (-Fc) of both databases, the uploads archive, a copy of the erasure ledger, row counts and a
# SHA-256 manifest -> <out>/<UTC timestamp>/, then <out>/last-backup.json (read by the app's backup-age alert).
# Backups contain personal data: <out> is git-ignored. Retention: BACKUP_RETENTION_DAYS (default 30).
#
# Usage: scripts/backup.sh [-p compose_project] [-e env_file] [-o out_dir]
#   defaults: -p decisionops  -e .env  -o backups     (run from anywhere; paths are relative to the repo root)
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PROJECT=decisionops
ENV_FILE="$ROOT/.env"
OUT="$ROOT/backups"
while getopts "p:e:o:" opt; do
  case $opt in
    p) PROJECT=$OPTARG ;;
    e) ENV_FILE=$OPTARG ;;
    o) OUT=$OPTARG ;;
    *) echo "usage: $0 [-p project] [-e env_file] [-o out_dir]" >&2; exit 2 ;;
  esac
done
RETENTION=${BACKUP_RETENTION_DAYS:-30}
export MSYS_NO_PATHCONV=1 # Git Bash on Windows: keep container paths as written...
if command -v cygpath >/dev/null 2>&1; then # ...so host paths must be given to docker in Windows form
  ROOT=$(cygpath -m "$ROOT"); ENV_FILE=$(cygpath -m "$ENV_FILE"); OUT=$(cygpath -m "$OUT")
fi

dc() {
  if [ -f "$ENV_FILE" ]; then docker compose -f "$ROOT/compose.yaml" -p "$PROJECT" --env-file "$ENV_FILE" "$@"
  else docker compose -f "$ROOT/compose.yaml" -p "$PROJECT" "$@"; fi
}

STARTED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
TS=$(date -u +%Y%m%dT%H%M%SZ)
DIR="$OUT/$TS"
mkdir -p "$DIR"
echo "Backing up project '$PROJECT' to $DIR"

for db in decisionops decisionops_demo; do
  dc exec -T db sh -c "pg_dump -U postgres -Fc -f /tmp/$db.dump $db"
  dc cp "db:/tmp/$db.dump" "$DIR/$db.dump"
  dc exec -T db rm -f "/tmp/$db.dump"
done

dc exec -T api sh -c 'mkdir -p /data/uploads /data/ledger && tar czf /tmp/uploads.tar.gz -C /data uploads'
dc cp api:/tmp/uploads.tar.gz "$DIR/uploads.tar.gz"
dc exec -T api rm -f /tmp/uploads.tar.gz
# The erasure ledger is also kept outside the database dump, so a restore can always re-apply erasures.
dc exec -T api sh -c 'cat /data/ledger/erasure-ledger.jsonl 2>/dev/null || true' > "$DIR/erasure-ledger.jsonl"

COUNTS_SQL="select json_object_agg(t, n) from (
  select 'app_user' t, count(*) n from app_user union all select 'decision', count(*) from decision
  union all select 'evidence_snapshot', count(*) from evidence_snapshot union all select 'evidence_item', count(*) from evidence_item
  union all select 'document', count(*) from document union all select 'chunk', count(*) from chunk
  union all select 'order_ticket', count(*) from order_ticket union all select 'audit_event', count(*) from audit_event
  union all select 'share_grant', count(*) from share_grant union all select 'erasure_ledger', count(*) from erasure_ledger) x"
COUNTS=$(dc exec -T db psql -U postgres -d decisionops -Atc "$COUNTS_SQL" | tr -d '\r')
REVISION=$(dc exec -T db psql -U postgres -d decisionops -Atc "select version_num from alembic_version" | tr -d '\r')

(cd "$DIR" && sha256sum decisionops.dump decisionops_demo.dump uploads.tar.gz erasure-ledger.jsonl > SHA256SUMS)
COMPLETED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
FILES=$(cd "$DIR" && awk '{printf "%s{\"name\":\"%s\",\"sha256\":\"%s\"}", (NR>1?",":""), $2, $1}' SHA256SUMS)
cat > "$DIR/manifest.json" <<EOF
{"format": 1, "project": "$PROJECT", "started_at": "$STARTED", "completed_at": "$COMPLETED",
 "alembic_revision": "$REVISION", "counts": $COUNTS, "files": [$FILES], "retention_days": $RETENTION}
EOF
cat > "$OUT/last-backup.json" <<EOF
{"completed_at": "$COMPLETED", "path": "$TS", "project": "$PROJECT", "counts": $COUNTS}
EOF

# Retention: remove timestamped backup folders older than the window (never anything else).
find "$OUT" -mindepth 1 -maxdepth 1 -type d -name '20[0-9][0-9][01][0-9][0-3][0-9]T*Z' -mtime +"$RETENTION" -exec rm -rf {} + 2>/dev/null || true

echo "Backup complete: $DIR"
echo "  counts: $COUNTS"
echo "  verify later with: (cd \"$DIR\" && sha256sum -c SHA256SUMS)"
