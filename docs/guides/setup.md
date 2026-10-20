# Setup

## Requirements

- Docker Desktop (Compose v2). Nothing else is needed for the core product.
- Optional: [Ollama](https://ollama.com) on the host with `qwen3:4b` (≈2.5 GB) for model-enabled runs.
- For development checks only: Node.js 22 + npm, Git Bash or PowerShell 7, Trivy.

## Start

```sh
cp .env.example .env          # set the DB passwords; optionally OWNER_EMAIL / OWNER_PASSWORD
docker compose up --build -d
```

Open <http://127.0.0.1:8087> (`APP_PORT` in `.env`). The first start builds images, runs migrations and seeds
synthetic data. A startup page shows component readiness until the API is ready.

- **Owner account:** created on first start from `OWNER_EMAIL` / `OWNER_PASSWORD` if set (read only by `migrate`,
  only when no owner exists). Otherwise the setup screen asks for a one-time token:
  `docker compose exec api python -m app.cli setup-token`.
- **Demo:** <http://127.0.0.1:8087/demo/>, `demo@example.com` / `demo-read-only` (public on purpose; synthetic,
  read-only; change with `DEMO_USER_EMAIL` / `DEMO_USER_PASSWORD`).
- **Stop:** `docker compose down` keeps data. `docker compose down -v` **deletes** the database and uploads.
- **Private owner note:** the owner keeps a personal `.admin-user` file in the repository root (owner URL, sign-in
  email, display name and the current password, plus change/recovery instructions). It is excluded from Git and from
  Docker build contexts and readable only by the owner's Windows account. Never commit, copy or share it, and update
  it yourself after changing the password in the app (nothing updates it automatically).
- **Recovery:** recovery codes (if TOTP is enabled) or
  `docker compose exec api python -m app.cli reset-owner-password`. See Help → *First run and recovery*.

## Configuration

All settings are environment variables; `.env.example` lists them with placeholders. Notable ones:

| Variable | Default | Effect |
| --- | --- | --- |
| `APP_PORT` | `8087` | Local port (bound to 127.0.0.1) |
| `EMBEDDINGS_ENABLED` | `false` | `true` downloads `BAAI/bge-small-en-v1.5` once and adds vector retrieval; `false` = keyword (FTS) only |
| `OLLAMA_BASE_URL` / `MODEL_NAME` | `http://host.docker.internal:11434` / `qwen3:4b` | Model mode is offered only when the readiness probe passes |
| `LIVE_TRADING_ENABLED` | off | Live is not authorized in this build; the API refuses it regardless |
| `IBKR_*`, `ZOOM_*` | unset | Optional integrations; unset = shown as externally unverified |

`.env` holds real secrets. It is git-ignored and excluded from images (`.dockerignore`).

## Offline operation

| Phase | Network needed? | What is downloaded |
| --- | --- | --- |
| First build / first run | **Yes** | Base images (PostgreSQL+pgvector, Python, Node, Caddy) and Python/npm dependencies at build time |
| Embeddings (optional) | Once | fastembed model into the app data volume, only if `EMBEDDINGS_ENABLED=true` |
| Chat model (optional) | Once | `qwen3:4b` via host Ollama, only if the owner chooses |
| **After setup** | **No** | Mock mode, deterministic workflows, keyword retrieval, calendars, collaboration data, Help, ops and the demo work offline |
| External integrations | Always | IBKR, Zoom API: shown as unavailable when offline, never faked |

A fully offline *first* run is not supported (images must be pulled or loaded with `docker save`/`docker load`).

**How offline-after-setup was verified (20 Oct 2026):** the isolated E2E stack was started with
[`deploy/compose.offline-test.yaml`](../../deploy/compose.offline-test.yaml), which puts `db`, `api`, `worker` and
`api-demo` on an `internal: true` Docker network (no route out; only `web` keeps the published port). Probes from
the containers confirmed DNS, direct-IP HTTPS and host Ollama were unreachable. J2 (markets), J3 (deterministic
cycle), J6 (library + cited answer + removal) and J10 (demo) then passed. Evidence:
[testing/evidence-2026-10-20.md](../testing/evidence-2026-10-20.md).

## Development

- Backend tests run in Docker (Windows Application Control blocks SQLAlchemy's compiled extensions on this host):
  `scripts/check.sh` / `scripts/check.ps1` builds the test image and runs everything against a throwaway Postgres.
- Frontend: `cd frontend && npm ci && npm run dev` (proxy to a running stack), `npx vitest run`, `npx tsc -b`.
- API types: `python -m app.cli openapi > frontend/openapi.json` then `npm run gen:api`; the checks runner fails
  if either file is stale.
- E2E: see [testing/README.md](../testing/README.md).
