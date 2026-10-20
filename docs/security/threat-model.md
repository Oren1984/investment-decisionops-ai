# Threat model (STRIDE-lite)

Scope: one owner on their own machine, optional invited collaborators, a local read-only demo. The app listens on
127.0.0.1 only. Local machine access is the trust anchor (it can reset the owner password via the CLI).

| Area | Threats | Controls (implemented) | Evidence |
| --- | --- | --- | --- |
| Authentication | Credential stuffing, session theft, CSRF, fixation | Argon2id hashing; login rate limit (generic errors, 15-min backoff); server-side sessions in PostgreSQL; HttpOnly `SameSite=Strict` cookies (`Secure` when `COOKIE_SECURE=true`); CSRF token header on unsafe methods; session rotation on login and step-up (rotation never extends the 12 h absolute lifetime); 30-min idle timeout; logout deletes the session; optional TOTP with hashed single-use recovery codes | `tests/integration/test_auth_and_authz.py`; J11 |
| Object access (IDOR) | Collaborator or demo reading owner objects | Every route declares exactly one permission (route-inventory test); object checks in services; collaborators see only explicit shares; revocation takes effect immediately, including open SSE streams (access re-checked per event) | Role × endpoint × foreign-ID matrix → 403/404; J9; `test_meeting_companion_shows_collaborators_only_notes_shared_with_them` (a meeting share does not expose its notes) |
| Demo isolation | Demo reaching owner data or writing | Separate database and read-only DB role with no grants on the owner DB; `APP_PROFILE=demo`; unsafe methods refused; no uploads volume, no secrets; owner and demo sessions rejected by each other's API | `test_demo_and_bootstrap.py`; J10; main-stack smoke (401 both ways) |
| Broker execution | Unapproved, duplicate, replayed or wrong-mode orders; stale prices | Payload-hash-bound approval with step-up and 5-min expiry; idempotent client order IDs; limits; stale-quote block; uncertain → reconcile before retry; Live refused | Mock scenario suite; J7, J8 |
| Agents / MCP | Over-privileged tools, cross-scope access, proposals treated as commands | Read/compute-only tools; per-run capability tokens with scope and expiry; per-role budgets; stdio only; proposals stored inert | Tool-permission and "proposal never executes" tests |
| Prompt injection | Documents steering agents | Retrieved text delimited as data; no consequential tools exist; schema validation; critic flags instruction-like content | Injection fixtures |
| File uploads | Malicious/huge files, parser DoS, traversal | Allowlist + magic bytes; size/quota caps; random storage IDs in a non-served directory; parsing in the worker | Upload fixture tests |
| Deletion / erasure | Residual content; restore resurrecting erased data | Erasure across DB, files and index; evidence redaction with visible event; erasure ledger in DB **and** outside the dump; replay before the app starts after restore | `test_deletion.py` (incl. CLI replay in a fresh process); restore test on isolated stack, 20 Oct 2026 |
| Secrets | Leaks via git, images, logs, screenshots | `.env`, `.admin-user`, other credential/personal files, logs, test credentials and reports excluded by `.gitignore` **and** `.dockerignore`; the Docker build context contains only what the images need; integration secrets encrypted at rest; log redaction; gitleaks; screenshots from the demo only | gitleaks clean; build-context inspection and `git check-ignore` (20 Oct 2026) |
| Meeting links | Stored links used for XSS (`javascript:`), phishing look-alikes, credential leakage or reaching local services | Server-side validation: https only, provider host must match (subdomain-safe, look-alike suffixes refused), no embedded credentials, no IP literals/localhost/internal names, standard port only, no whitespace/control characters, ≤ 2,048 chars; owner-only writes (demo and collaborators refused); the UI renders a link only if its protocol is `https:` and opens it with `target=_blank rel="noopener noreferrer"` | `test_meeting_links_for_each_provider`, `test_unsafe_or_mismatched_meeting_links_are_rejected`, `MeetingCard.test.tsx`, J12 (popup has no `window.opener`) |
| Web | XSS, clickjacking | React escaping; strict CSP (`default-src 'self'`, `frame-ancestors 'none'`, `object-src 'none'`); `X-Frame-Options: DENY`; `nosniff`; `Referrer-Policy: same-origin`; restrictive `Permissions-Policy`; COOP | `deploy/Caddyfile` |
| Availability (local) | One client stalling others | Permission check commits its session touch immediately, so long-lived SSE streams hold neither the session row lock nor a pooled connection | `test_permission_check_does_not_hold_the_session_row_lock`; live probe with 25 streams |
| Integrity (state after a response) | Client acts on a 200 whose write is not yet committed (stale reads, lost actions such as an approval or removal not yet visible) | Every DB dependency is `Depends(get_db, scope="function")`, so the commit happens before the response is sent (FastAPI's default `"request"` scope commits after it) | `test_writes_are_committed_before_the_response_is_sent`; full E2E run (J6) |
| Supply chain | Vulnerable packages and base images | Lockfiles (`uv.lock`, `package-lock.json`); pinned images; pip-audit, npm audit, Trivy in `scripts/check`; reviewed exceptions expire | [dependency-findings.md](dependency-findings.md) |

## Residual risks

- The demo session is a stateless signed cookie valid 12 h; sign-out cannot revoke a copied cookie (synthetic,
  read-only data).
- Anyone with local administrative access to the machine can read the Docker volumes and reset the owner password.
- No external security review has been done. Any internet exposure needs enforced TOTP, TLS and a review first
  ([../deployment.md](../guides/deployment.md)).
