# Testing

Evidence logs use the four delivery statuses ([`PROJECT_PLAN.md`](../project/PROJECT_PLAN.md) §5). Latest: [evidence-2026-10-20.md](evidence-2026-10-20.md).

## Layers

| Layer | Where | How to run |
| --- | --- | --- |
| Lint + backend unit/integration/contract (real PostgreSQL) | `backend/tests/` | `scripts/check.sh` or `pwsh scripts/check.ps1` (builds the test image, throwaway Postgres on a private network) |
| Frontend unit (Vitest + Testing Library) | `frontend/src/**/*.test.ts(x)` | `cd frontend && npx vitest run` (also in the checks runner) |
| Types + API contract freshness | `frontend/openapi.json`, `src/api/schema.d.ts` | checks runner (`tsc -b`, regenerate-and-compare) |
| Security | — | checks runner: gitleaks, pip-audit, npm audit, Trivy |
| E2E (Playwright + axe) | `frontend/e2e/` | see below |
| Terraform static checks | `infra/terraform/lightsail/` | `terraform fmt -check`, `init -backend=false`, `validate`, `tflint` (containerized on this host; see [../deployment.md](../guides/deployment.md)) |

## E2E against an isolated stack

E2E never touches the owner's workspace. It runs against a separate Compose project on port 8097 with throwaway
credentials kept **outside the repository**:

```sh
# e2e.env (outside the repo): APP_PORT=8097, random POSTGRES_SUPERUSER_PASSWORD, APP_DB_PASSWORD,
# DEMO_OWNER_PASSWORD, DEMO_RO_PASSWORD, INITIAL_SETUP_TOKEN; DEMO_USER_EMAIL / DEMO_USER_PASSWORD
docker compose -p decisionops-e2e --env-file e2e.env down -v      # isolated project only, never the main one
docker compose -p decisionops-e2e --env-file e2e.env up -d
rm -f frontend/e2e/.auth/owner.json
cd frontend && E2E_SETUP_TOKEN=<token from e2e.env> npx playwright test
```

- Compose gives shell variables precedence over `--env-file`. A VS Code terminal with
  `python.terminal.useEnvFile: true` (`.vscode/settings.json`) exports the main `.env` (including `APP_PORT=8087`
  and the main passwords), so unset those keys for the E2E commands (`env -u APP_PORT -u APP_DB_PASSWORD … docker
  compose …`) or use a terminal without them; otherwise the E2E web container fails to bind 8087.
- Specs run in file order with one worker: J1 creates the owner; later specs reuse `frontend/e2e/.auth/owner.json`
  (git-ignored; J11 adds a TOTP secret and resets the password).
- J4 needs host Ollama with `qwen3:4b`; it is skipped (not failed) when the model is unreachable.
- `SCREENSHOTS=1 npx playwright test z-screenshots` refreshes `docs/screenshots/` from the **demo** instance.
- Delete `frontend/test-results/` after failures: snapshots can contain the throwaway password.

## Journeys

| Spec | Covers |
| --- | --- |
| J1 | First run: setup token (wrong token rejected, single use), owner creation, Mock + Synthetic badges |
| J2 | Venue clocks, session state, countdowns, calendar (XTKS, XNYS) |
| J3 | Deterministic research cycle → frozen evidence → decision |
| J4 | Model-enabled cycle with real `qwen3:4b`: cancel mid-run, resume, no duplicate steps, model/prompt recorded |
| J5 | Replay and review with a lesson |
| J6 | Upload, cited answer, remove from library, no longer retrieved |
| J7 | Mock order: preview, step-up approval, duplicate-safe submit, partial fill |
| J8 | Stop blocks submissions and runs; cancel-open-orders is separate |
| J9 | Invite, accept, share, comment, dual-timezone meeting, revoke |
| J10 | Demo sign-in, read-only UI and API, isolation from the owner workspace |
| J11 | TOTP sign-in, recovery code, CLI password reset |
| J12 | Meeting links: schedule with Microsoft Teams, edit to Google Meet (mismatched and `javascript:` links refused), Open meeting opens a new tab without `window.opener`; demo shows links but cannot add/edit (UI and API 403). External hosts are intercepted |
| J13 | Sign-out, owner and demo: sign-in shows at once without a reload, session ends server-side (401), browser Back and protected URLs show only sign-in |
| k01 | axe (WCAG 2.1 A/AA) on 10 owner pages, sign-in and demo; keyboard skip link; no horizontal overflow at 360/768/1280/1920; Help links resolve; charts render |

## Ops checks (manual procedures, recorded in evidence logs)

- Restart persistence: row counts before/after `docker compose up -d --build` and `docker compose restart`.
- Backup → erase → restore → erasure stays applied → `verify-evidence` → app starts (isolated project only).
- Offline after setup: `deploy/compose.offline-test.yaml` overlay on the isolated project, then J2/J3/J6/J10.
