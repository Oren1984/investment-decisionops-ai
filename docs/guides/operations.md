# Operations

## Start, stop, update

```sh
docker compose up -d --build   # start or update; volumes are kept
docker compose restart         # restart all services; data persists (verified 20 Oct 2026)
docker compose down            # stop; data kept
docker compose down -v         # DELETES the database and uploads
```

Data lives in two named volumes: `decisionops_pgdata` (both databases) and `decisionops_appdata` (uploads,
erasure-ledger file, optional embedding model cache).

## Backup

```sh
scripts/backup.sh                     # Git Bash / Linux / macOS
pwsh scripts/backup.ps1               # PowerShell 7
# options: -p/-Project <compose project>  -e/-EnvFile <env file>  -o/-OutDir <dir>   (defaults: decisionops, .env, backups)
```

Writes `backups/<UTC timestamp>/` (git-ignored; contains personal data): `pg_dump -Fc` of `decisionops` and
`decisionops_demo`, `uploads.tar.gz`, a separate copy of `erasure-ledger.jsonl`, `manifest.json` (row counts,
Alembic revision) and `SHA256SUMS` (same format from both scripts; verify with `sha256sum -c SHA256SUMS`). It then
updates `backups/last-backup.json`, which the app reads (mounted read-only) for the **backup older than 26 h**
alert. Timestamped folders older than `BACKUP_RETENTION_DAYS` (default 30) are removed; nothing else is touched.

Schedule it yourself (Windows Task Scheduler or cron); the app does not run backups. Copy backups off the machine
if they must survive a disk loss.

## Restore

```sh
scripts/restore.sh backups/<timestamp>            # asks you to type the project name
pwsh scripts/restore.ps1 backups\<timestamp>
```

Destructive: replaces both databases and the uploads. Order:

1. verify checksums (abort before any change if damaged);
2. typed confirmation (`-y` / `-Yes` only for scripted tests on an isolated project);
3. stop `web`, `api`, `api-demo`, `worker` (the DB keeps running);
4. `dropdb --force` + `pg_restore --create` for both databases;
5. restore uploads through a helper container;
6. run migrations;
7. **replay the erasure ledger**: the backup's copy, then the live ledger (which may hold erasures newer than the
   backup);
8. print row counts next to the manifest's, run `python -m app.cli verify-evidence` (recomputes frozen-evidence
   hashes) and **start the app only if it passes**.

Never restore into the main project to "test" a backup: use an isolated project (`-p decisionops-e2e` with its own
env file) as in [testing/evidence-2026-10-20.md](../testing/evidence-2026-10-20.md).

## Erasure ledger

Every document removal or erasure appends an entry to the `erasure_ledger` table **and** to
`/data/ledger/erasure-ledger.jsonl` in the app volume (outside the database dump). `python -m app.cli
replay-erasure-ledger [--path <file>]` re-applies all entries idempotently: deletes resurrected documents, chunks
and files and re-redacts evidence items. The restore scripts run it before the app becomes reachable, so a restore
from an older backup cannot resurrect erased content. Verified on 20 Oct 2026 by erasing a document after a backup,
restoring that backup and confirming the document, its chunks and file were gone again and evidence still verified.

## Alerts

Evaluated by the worker every minute; each links to a Help article (`help/alert-*.md`): worker heartbeat lost,
order uncertain > 2 min, reconciliation mismatch, stale feed, backup older than 26 h, login-failure spike, model
unavailable while runs are queued.

## Health and metrics

- `/health/live`, `/health/ready` (database and migration revision, worker heartbeat), served through the proxy.
- `/metrics` (Prometheus text format) exists on the `api` container but requires an owner session (`read:ops`), and
  the proxy deliberately does not expose it. There is no unauthenticated scrape endpoint; the Ops page shows the
  same figures.
- Ops page in Settings: request error rate and latency, queue, run durations and agent usage per model, order
  states, reconciliation backlog, backup age.
- Logs: structlog JSON with correlation IDs; passwords, tokens, document text and prompts are not logged.

## CLI (inside the `api` container)

`docker compose exec api python -m app.cli <command>`: `setup-token`, `reset-owner-password [--email]`, `migrate
[--seed owner|demo]`, `index-help`, `replay-erasure-ledger [--path]`, `verify-evidence`, `purge`, `openapi`.

## Incident runbook

Stop (header button) → assess (Orders, Ops, audit) → reconcile → cancel open orders if needed (separate step) →
document → record lessons. See Help → *Approvals and Stop* and *Operations and alerts*.
