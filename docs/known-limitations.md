# Known limitations

## Integration status (same labels as Settings → Integrations)

| Integration | Status | Why |
| --- | --- | --- |
| Mock broker adapter | Implemented and verified locally | Simulated execution with failure scenarios; not a real broker |
| Interactive Brokers — Paper | **Implemented but externally unverified** | No IBKR account or IB Gateway configured; contract-tested against a fake client only |
| Interactive Brokers — Live | **Not implemented or blocked** | Not authorized; the API refuses Live |
| Zoom scheduling (Server-to-Server OAuth) | **Implemented but externally unverified** | No Zoom app configured; tested against a fake Zoom API (httpx MockTransport) only |
| Meeting links (Zoom, Google Meet, Microsoft Teams, other https) and simulated meetings | Implemented and verified locally | Links are validated, saved and opened in a new tab; this verifies the app's handling of links, not the meeting services themselves (no provider API is called). Simulated meetings never connect a real call |
| Embedded meeting video | **Not implemented** (not required) | Owner decision D-A (20 Oct 2026): meetings open in the provider's own tab or app |
| Google Meet / Microsoft Teams scheduling APIs | **Not implemented** (not required) | Decision D-A: paste their links; only Zoom has optional API scheduling |
| Local chat model (Ollama, `qwen3:4b`) | Implemented and verified locally (isolated E2E stack, 20 Oct 2026) | Each instance shows "Model not run on this machine yet" until model mode runs there once |
| Local embeddings (fastembed) | Disabled by default | `EMBEDDINGS_ENABLED=false`: keyword search only. The hybrid (vector) path is evaluated only when embeddings are enabled, which was not done in this verification |
| Market data | Implemented and verified locally (synthetic only) | No real market-data feed is configured or claimed |
| Exchange calendars | Implemented and verified locally | Offline library; accuracy depends on the installed `exchange_calendars` release |
| Economic calendar feed (FRED) | **Not implemented or blocked** | Optional enhancement, not built; events are user-entered or Mock |
| Deployment (Terraform, Lightsail) | Static checks only | `plan`/`apply` not authorized; server TLS override not written ([deployment.md](guides/deployment.md)) |

## Product and engineering limitations

- **Model tool use:** under schema-constrained JSON (needed for acceptable latency on this CPU-only machine) the
  model seldom calls MCP tools itself; evidence is gathered by the computed step through the same MCP gateway and
  placed in the prompt. Details: [agents-and-mcp.md](architecture/agents-and-mcp.md#known-limitation-model-tool-use).
- **Model mode depends on the host Ollama app running.** If it is stopped, model mode is not offered (an alert
  fires if runs are queued); the deterministic mode always works.
- **Model-mode speed:** a full model cycle took ~7 minutes on this machine (CPU, `qwen3:4b`).
- **Demo session is a stateless signed cookie (12 h)** because the demo DB role is read-only. Sign-out clears it in
  the browser, but a copied cookie stays valid until expiry. Impact is low: synthetic, read-only data.
- **Response types are hand-written** in the frontend (`src/api/types.ts`); only request bodies are generated from
  OpenAPI. A backend response change is caught by tests and E2E, not by the compiler.
- **Evidence checks are heuristics** (lexical, not semantic). See [rag.md](architecture/rag.md#evidence-checks-what-they-are-and-are-not).
- **No email:** invitations are links the owner sends manually; password recovery is via recovery codes or the CLI.
- **Backups are not scheduled by the app**; the owner schedules `scripts/backup.*` and keeps copies off-machine.
- **Single owner** by design; collaborators see only what is explicitly shared.
- **Dependency findings with no available fix** are listed in
  [security/dependency-findings.md](security/dependency-findings.md) (chromadb and mcp via crewai; Debian base
  packages; three Go findings in the official Caddy binary).
- **Playwright failure snapshots** (`frontend/test-results/`, git-ignored) can contain the throwaway E2E password
  in form fields. Delete them after runs; never attach them to documents.
- **Sign-out edge cases:** if the logout request itself fails (server unreachable), the browser still drops its
  cached data and shows sign-in, but the server session stays valid until its idle or absolute timeout. A copied demo
  cookie stays valid for up to 12 h (see above).

## Verification limits (V1.0, 20 Oct 2026)

What was and was not re-verified for the final V1.0 changes. Exact commands and results:
[testing/evidence-2026-10-20.md](testing/evidence-2026-10-20.md).

- **Unexplained one-off E2E failure.** After the last Help Center tweak, one k01 check (axe on `/markets`) failed
  once: an API call returned HTML (`<!doctype …`) instead of JSON. It passed twice on its own and in a complete
  re-run of `j13 k01` (20/20). The cause was not found and it was not reproduced; the most likely explanation is a
  transient proxy response shortly after the web container was recreated, but that is **not proven**. Re-run k01 if
  it appears again and keep the trace.
- **Full regression suite not re-run for the final frontend changes.** The last full Playwright run (31 passed,
  1 skipped) and both checks runners (11/11) predate the sign-out fix, Help Center, sign-in screen and credit change.
  Those changes are frontend-only; they were verified with `tsc -b`, Vitest (25/25), J10, J12, J13 and k01 on the
  isolated stack, and with a smoke test and UI sign-out checks on the main stack.
- **Backend images not rebuilt** for the final changes (no backend change); the security scans (pip-audit, Trivy)
  were last run on the afternoon build.
- **Browsers:** E2E and screenshots use Playwright's Chromium only; Firefox and Safari were not tested. Back/forward
  cache behaviour differs by browser; the reload-on-restore guard was exercised only indirectly.
- **Not verified against real providers:** IBKR Paper, Zoom API, real market data, embeddings-enabled retrieval;
  nothing was deployed.
