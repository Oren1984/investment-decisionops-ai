---
title: Troubleshooting
category: Operations
summary: Common errors and how to fix them.
routes: /settings
---
| Symptom | Fix |
| --- | --- |
| “Cannot reach the server” | `docker compose ps`; restart with `docker compose up -d` |
| Port in use | Set `APP_PORT` in `.env` and restart |
| Page shows “starting” for long | `docker compose logs migrate api` — migrations or seed may have failed |
| “Security check failed” | Reload the page (your session or CSRF token expired) |
| “Confirm it's you” | Approvals need a fresh password confirmation |
| Model mode unavailable | See [Local model](/help/local-model) |
| Quotes stale | The worker refreshes them; check the worker alert |
