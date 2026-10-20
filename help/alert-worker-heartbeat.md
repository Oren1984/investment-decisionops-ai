---
title: Alert: worker heartbeat lost
category: Alerts
summary: The background worker stopped reporting.
routes: /settings
---
The worker runs research, ingestion, reconciliation and quote refresh. Without it, runs stay queued and quotes go stale.

1. `docker compose ps worker` and `docker compose logs --tail 100 worker`.
2. Restart: `docker compose restart worker`.
3. Runs that were in progress become **Interrupted**; press **Resume** on the decision's Agent runs tab.
