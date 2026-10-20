# Tasks

Statuses are the four from `PROJECT_PLAN.md` §5. Evidence: `docs/testing/evidence-2026-10-20.md` (E) unless noted.

| Area (milestone) | Status | Evidence | Blocker / next action |
| --- | --- | --- | --- |
| Platform: Compose stack, migrations, seed, startup page (M1) | Implemented and verified locally | Clean start of the isolated stack; main stack deploy + restart persistence; request transaction commits before the response (`test_writes_are_committed_before_the_response_is_sent`, full E2E run) (E) | — |
| Identity: sessions, CSRF, step-up, TOTP, recovery, CLI reset, sign-out (M1) | Implemented and verified locally | Backend auth tests; J1, J11; J13 sign-out (owner + demo; Back and protected URLs); `session.test.tsx` (E) | — |
| Authorization matrix, route inventory (M1) | Implemented and verified locally | `test_auth_and_authz.py` (E) | — |
| Markets, clocks, calendars (M2) | Implemented and verified locally (offline calendar library; synthetic quotes) | Controlled-time unit tests; J2 (E) | Real market data: not configured |
| Portfolio, manual holdings, exposure (M3) | Implemented and verified locally (Mock/synthetic) | J1, k01 charts (E) | — |
| Decision records, frozen evidence, replay, corrections, reviews (M4) | Implemented and verified locally | J3, J5; integration tests (E) | — |
| Deterministic workflow (CrewAI Flow) (M4) | Implemented and verified locally | J3 (E) | — |
| Knowledge library, FTS retrieval, extractive answers, evidence heuristics (M5) | Implemented and verified locally | RAG evaluation; J6 (E) | Embeddings path not enabled in this verification |
| Deletion modes + erasure ledger (M5) | Implemented and verified locally | `test_deletion.py`; restore test (E) | — |
| Model-enabled agents on local Ollama (M6) | Implemented and verified locally | J4 with real `qwen3:4b` on the isolated stack (E) | Limitation: model seldom calls MCP tools under JSON mode (`docs/architecture/agents-and-mcp.md`) |
| MCP tool server, capability tokens, budgets (M6) | Implemented and verified locally | Tool-permission tests (E) | — |
| Mock broker, orders, approvals, limits, reconciliation, Stop (M7) | Implemented and verified locally | Mock scenario suite; J7, J8 (E) | — |
| IBKR adapter (Paper) (M7) | Implemented but externally unverified | Contract tests against a fake client | Owner decision to open/configure an IBKR account (D1) |
| Live trading (M7) | Not implemented or blocked | API refuses Live | Not authorized |
| Collaboration: invites, shares, comments, action items, revocation (M8) | Implemented and verified locally | J9; authz matrix (E) | — |
| Meetings: links for Zoom, Google Meet, Microsoft Teams and other https; provider selection; save/edit; Open meeting in a new tab; simulated meetings; dual-timezone display (M8, D-A) | Implemented and verified locally | Link-validation tests; `MeetingCard.test.tsx`; J9, J12 in the full afternoon E2E run; main smoke 21/21 (E) | No provider API is called for Meet/Teams/other links (not required) |
| Zoom S2S scheduling (M8) | Implemented but externally unverified | Fake Zoom API tests | Owner Zoom app configuration |
| Embedded meeting video (M8) | Not implemented or blocked | — | Not required: owner decision D-A resolved 20 Oct 2026 |
| Help Center: topic groups, topic overview, highlighted selected article, breadcrumb, mobile article view; contextual links (M9) | Implemented and verified locally | k01 Help links, axe and 360–1920 px; `markdown.test.tsx` (nested lists, italics) (E) | — |
| Ops: alerts, health, Ops page, metrics, retention purge, export, delete-all (M9) | Implemented and verified locally | Integration tests; health checks (E) | — |
| Backup / restore scripts (sh + ps1) with ledger replay and evidence verification (M10) | Implemented and verified locally | Isolated-stack backup → erase → restore, both shells (E) | Owner schedules backups and keeps copies off-machine |
| Offline after setup (M10) | Implemented and verified locally | Internal-network overlay + J2/J3/J6/J10 (E) | — |
| Accessibility and responsive layout (M10) | Implemented and verified locally | k01: axe on 12 pages, keyboard, 360–1920 px (E) | — |
| Checks runner `scripts/check.(sh/ps1)` (M10) | Implemented and verified locally | Both runners, all steps passing (E) | — |
| Security scans (M10) | Implemented and verified locally | `docs/security/dependency-findings.md` | Reviewed exceptions: mcp/chromadb via crewai; Debian unfixed; Caddy Go stdlib (expires 31 Dec 2026) |
| Terraform module, AWS Lightsail (M10) | Implemented but externally unverified (static checks only) | fmt, validate, tflint (E) | `plan`/`apply` not authorized; owner decision D-B; server TLS Compose override not written |
| Documentation, screenshots (M10) | Implemented and verified locally | `README.md` (What / Why / How), `docs/README.md` index, `docs/project/` (plan, tasks, decisions), local-only `docs/internal/`; `docs/screenshots/` from the demo (refreshed 20 Oct evening: V1.0 credit, new Help Center); links checked (E) | — |
| Git/Docker exclusions for credentials, personal files, logs, temp files, test credentials and reports | Implemented and verified locally | `git check-ignore`, build-context inspection, image scan (E) | — |
| Private owner note `.admin-user` (owner request) | Implemented and verified locally | Excluded from Git, build context and images (verified 20 Oct evening); URL, username and password verified by a real sign-in (E) | — |
| FRED economic calendar feed (optional) | Not implemented or blocked | — | Optional enhancement, not approved |
