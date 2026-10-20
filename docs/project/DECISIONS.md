# Decisions (ADR-lite)

Newest last. Owner decisions are marked **Owner**; implementation decisions record the reason and the
deviation from `PROJECT_PLAN.md` where there is one.

## Owner decisions (18 Oct 2026, plan §4)

| ID | Decision |
| --- | --- |
| D1 Broker | IBKR is the proposed first real adapter, subject to verification. No account, funding, gateway or subscription is authorized or assumed; IBKR stays "Implemented but externally unverified" |
| D2 TASE | Reference data, calendars and manual holdings only; no TASE execution; adapter interface kept venue-agnostic; no second broker |
| D3 Zoom | Links, scheduling, manual links and dual-timezone display committed; embedded video was open decision **D-A** (resolved 20 Oct, below) |
| D4 Terraform | Compare providers from official sources, recommend one, no provisioning or spending; recommendation AWS Lightsail; final target is open decision **D-B** |
| D5 Model | Recommend from actual hardware, no installs: `qwen3:4b` default |
| D6 Demo | Local-only, synthetic, strictly isolated |
| D7 Deletion | Two explicit modes: remove (keep frozen quotations) and erase (redact everything, minimal non-content audit record, visible redaction) |
| D8 Planning files | Brief unmodified at the root; `PROJECT_PLAN.md` is the single authoritative plan |

## Later decisions and deviations

| Date | Decision | Why |
| --- | --- | --- |
| 19 Oct | **Owner:** local port **8087** | Owner instruction (plan suggested a configurable default) |
| 19 Oct | **Owner:** the demo requires sign-in with one published read-only account in the isolated demo DB | Owner request; demo session is a stateless signed cookie because the demo DB role is read-only |
| 19 Oct | **Owner:** owner account bootstrapped from `.env` (`OWNER_EMAIL`/`OWNER_PASSWORD`), read only by `migrate` and only when no owner exists | Owner request; setup-token flow remains for fresh installs |
| 19 Oct | Backend development and tests run in Docker | Windows Application Control blocks SQLAlchemy's compiled extensions on the host |
| 19 Oct | `order` merged into `order_ticket`; resubmission after NotFound gets a new client order ID | One record per intent keeps idempotency simple |
| 19 Oct | Own small UI kit on Radix primitives instead of shadcn/ui; own Zod resolver; TypeScript pinned 5.9.3 | Fewer generated files and dependencies; resolver compatibility with Zod 4 |
| 19 Oct | Response types hand-written (`src/api/types.ts`); request bodies typed from generated OpenAPI (`src/api/contract.ts`) | The backend returns plain dicts for responses; request schemas are precise |
| 19 Oct | Demo API computes synthetic quotes on read | The demo DB role is read-only |
| 19 Oct | `chunk.doc_title` included in the FTS vector; abstention threshold: coverage 0.4 | Measured on the RAG evaluation set (recall@5 0.97, MRR 0.97) |
| 19 Oct | Model calls: `ollama_chat/` + schema-constrained JSON + reasoning disabled | Measured latency on this CPU-only machine (~150 s/call free-form vs seconds with JSON); consequence: agents seldom call MCP tools themselves (documented limitation) |
| 19 Oct | Logout uses `perm("public")` and resolves the principal itself | Demo principals may not use unsafe methods, but must be able to sign out; CSRF still enforced for real sessions |
| 19 Oct | E2E runs against an isolated Compose project (`decisionops-e2e`, port 8097) | Keeps the owner's workspace untouched |
| 20 Oct | The permission dependency commits the session touch immediately | Root cause of the intermittent E2E "all requests hang" (J7 on 19 Oct, J1 on 20 Oct): SSE streams kept the request transaction open, holding the session row lock and a pooled connection |
| 20 Oct | All CLI commands register every ORM model at start | `replay-erasure-ledger` failed in a fresh process (`NoReferencedTableError`), which would have stopped a restore at the ledger step |
| 20 Oct | Web image on `caddy:2.11.7-alpine`; `uv` not shipped in the app runtime image | 98 → 4 fixable image findings; remaining exceptions documented in `docs/security/dependency-findings.md` |
| 20 Oct | `mcp` stays 1.28.1 and `chromadb` 1.5.9 despite advisories | `crewai` 1.15.28 (latest) pins `mcp<1.29`; advisories affect the HTTP server transport / Chroma server, neither used. Revisit on the next crewai release |
| 20 Oct | Offline-after-setup verified with an `internal: true` network overlay on the isolated stack | Disabling the host network would disrupt the owner; the overlay removes all egress for backend services |
| 20 Oct | Terraform static checks run in the official `hashicorp/terraform` container | The native binary's provider handshake fails on this host (`x509: certificate signed by unknown authority`) |
| 20 Oct | **Owner — D-A resolved:** meetings support Zoom, Google Meet, Microsoft Teams and other https meeting links. The owner picks the provider, saves or edits the link, and joins with **Open meeting**, which opens a new browser tab. **No embedded video and no additional provider API integrations** (Google/Microsoft) are required. Existing Zoom functionality (manual Zoom links, optional Zoom S2S scheduling, simulated meetings) is preserved | Owner instruction. Implementation: `meeting.link_provider` (migration 0003; existing links backfilled as Zoom), server-side validation (https only, provider host must match, no credentials/IP/localhost/odd ports/whitespace, ≤ 2,048 chars), `rel="noopener noreferrer"`, links rendered only if `https:` |
| 20 Oct | Private owner note `.admin-user` (repository root) holds the owner URL, email, display name and password instructions, **without the password** (it points to `OWNER_PASSWORD` in `.env`) | Owner request. Excluded from Git (`.gitignore`) and Docker (`.dockerignore`), both verified; Windows ACL limited to the owner's user |
| 20 Oct | `.gitignore` / `.dockerignore` extended (credentials, personal account files, logs, temp/debug files, test credentials, generated reports, build caches); Docker build context reduced to what the images need | Owner request. The web build context previously included the E2E test credentials file (build stage only, not the shipped image) |
| 20 Oct | Every `Depends(get_db)` uses `scope="function"` (125 call sites), so the request transaction commits **before** the response is sent | FastAPI's default `"request"` scope ran `get_db`'s commit after the response, so a client could act on a 200 before the change was visible (root cause of the J6 failure in a full E2E run). Regression test `test_writes_are_committed_before_the_response_is_sent` fails without the fix and passes with it |
| 20 Oct | **Owner:** `.admin-user` now also contains the owner password (supersedes "without the password" above). The value is the existing `OWNER_PASSWORD` from `.env`, verified by a real sign-in before and after writing; the account was not reset or changed | Owner request (the file should hold the URL, username and a working password). Still excluded from Git, the build context and images (verified); Windows ACL owner-only; edited in place so the ACL was kept |
| 20 Oct | Docs regrouped: `docs/guides/` (setup, operations, deployment), `docs/architecture/` (overview, agents and MCP, RAG, broker), `docs/security/` (+ governance, regulatory notes); new `docs/README.md` index; README rewritten as What / Why / How. Planning/agent files and the brief stay at the root (AGENTS.md, D8); `help/` and `seed/docs/` stay because the app reads them. No `docs/archive/`: the only dated report (`docs/testing/evidence-2026-10-20.md`) is the current evidence for `TASKS.md` and follows the `AGENTS.md` naming convention | Owner request for a small, clear structure; links checked (100 relative links, 0 broken) |
| 20 Oct | **Owner:** `PROJECT_PLAN.md`, `TASKS.md`, `DECISIONS.md` → public `docs/project/`. `HANDOFF.md` and the original brief → local-only `docs/internal/` (excluded by `.gitignore` and `.dockerignore`). **Supersedes D8 only for the brief's location**; its content is unchanged (SHA-256 identical before and after the move). Root keeps `README.md`, `AGENTS.md`, `CLAUDE.md` | Owner request. `AGENTS.md` reads the local HANDOFF if present; public docs no longer link to the internal files. Neither internal file was ever committed, so they are not in Git history |
| 20 Oct | Sign-out clears the client in place: the `["auth"]` cache entry is set to signed-out and all other cached responses are removed, then the router replaces the current history entry. Any 401 re-checks auth; a page restored from the back/forward cache reloads | Root cause of "Logout leaves the screen until a refresh": `queryClient.clear()` removed the auth query that the mounted App was observing, so the following `invalidateQueries(["auth"])` had nothing to refetch. Demo sign-out hard-navigated to `/` (the owner app) instead of the demo sign-in. Regression: J13 (fails on the old build, passes on the new one) and `session.test.tsx` |
| 20 Oct | Meeting companion lists only the notes a collaborator may see (owner: all; collaborator: notes with their own grant). A meeting share does not cover its notes | Found by an automated security review after the V1.0 commit: the companion endpoint returned every note attached to a shared meeting, while `/shared` and the linked decision already required their own grant. Regression test fails without the fix (owner-only note and body returned) and passes with it |

## Open owner decisions

- **D-B:** deployment target confirmation (recommendation: AWS Lightsail, Frankfurt, 4 GB) and whether to deploy at all.
- Whether to configure IBKR Paper and/or a Zoom app (each would move that integration toward "Verified against a real configured provider").
