---
title: Operations: health, dashboard, backups
category: Operations
summary: Health checks, the ops dashboard, alerts, backup and restore.
routes: /settings
---
- `GET /health/live` and `/health/ready` report liveness and readiness.
- Settings → System shows error rate, p50/p95 latency, queue, run durations, agent usage, feed freshness, order states, reconciliation backlog, backup age and disk usage.
- Every alert links to a fix article.

## Backup and restore

- Backup: `scripts/backup.ps1` (Windows) or `scripts/backup.sh` — dumps both databases, the uploaded files and the erasure ledger to `./backups/<timestamp>/` with checksums.
- Restore: `scripts/restore.ps1 <folder>` — restores, then **re-applies the erasure ledger** so erased content cannot come back.
- `docker compose down` keeps your data. `docker compose down -v` **deletes it**.
