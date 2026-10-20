# Agent instructions

For any coding agent working in this repository.

## Read first

1. `docs/internal/HANDOFF.md`, **if present**: current state, running stacks, exact next steps. It is local-only
   (git- and docker-ignored, like the original brief next to it), so a fresh clone does not have it; continue from
   `docs/project/TASKS.md` then.
2. `docs/project/PROJECT_PLAN.md`: the single authoritative plan (status labels §5, journeys §6.4, testing §17).
3. `docs/project/TASKS.md` and `docs/project/DECISIONS.md`: what is done, with which status, and why things deviate
   from the plan.
4. `docs/README.md`: where the rest of the documentation lives. Public docs must not link to `docs/internal/`.

## Rules

- Use only the four delivery statuses from plan §5. Mock or simulated success never counts as broker, Zoom,
  market-data or model verification.
- Never run `docker compose down -v` on the main project (`decisionops`, port 8087): it deletes the owner's data.
  Destructive tests (restore, fresh E2E) run on the isolated project `-p decisionops-e2e` (port 8097) with an env
  file kept outside the repository.
- Never print or commit `.env` values or the contents of the owner's private `.admin-user` file (keep it excluded in
  both `.gitignore` and `.dockerignore`). Backups (`backups/`) and `frontend/test-results/` contain personal data or
  throwaway credentials and stay out of git and out of documents.
- No provisioning, deployment, `terraform plan/apply`, broker accounts or paid services without explicit owner
  approval. Live trading stays disabled.
- Backend tooling runs in Docker (`scripts/check.sh` / `scripts/check.ps1`); the host blocks SQLAlchemy's compiled
  extensions.
- Keep `frontend/openapi.json` and `src/api/schema.d.ts` regenerated when backend request schemas change (the
  checks runner fails otherwise).
- Documentation describes actual behaviour; record verification results with exact commands in
  `docs/testing/evidence-YYYY-MM-DD.md`.

## At session end

Update `docs/internal/HANDOFF.md` (real state only; create it if missing), `docs/project/TASKS.md` statuses and
`docs/project/DECISIONS.md` for any new decision or deviation.
Do not commit or push unless the owner asks.
