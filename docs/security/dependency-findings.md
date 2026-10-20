# Dependency and image findings (20 Oct 2026)

Produced by `scripts/check.(sh|ps1)`: pip-audit 2.9.0, `npm audit --omit=dev`, Trivy 0.74.0 (HIGH/CRITICAL),
gitleaks 8.29.1. The checks fail on any new finding; the exceptions below are reviewed and listed explicitly.

## Changes made today

| Change | Effect |
| --- | --- |
| Web image base `caddy:2.10-alpine` → `caddy:2.11.7-alpine` | Fixable HIGH/CRITICAL findings 98 → 4, i.e. 3 unique CVEs (Alpine 3.22.3 → 3.23.6, Caddy 2.10.2 → 2.11.7) |
| App image: `uv` installed only in the build stage; runtime stage copies the virtualenv | Removes the `uv` 0.11.7 binary (quinn-proto, rustls-webpki advisories) from the shipped image |

## Python (pip-audit)

| Package | Advisory | Fix | Why accepted |
| --- | --- | --- | --- |
| `mcp` 1.28.1 | GHSA-84m7-p3x7-pcfv | 1.30.0 | `crewai` 1.15.28 (latest release) requires `mcp<1.29`. The advisory concerns the **Streamable HTTP server** session store; this app runs MCP over **stdio** only (`mcp.run("stdio")`, `stdio_client`). Revisit when crewai allows mcp ≥ 1.30 |
| `chromadb` 1.5.9 | PYSEC-2026-311, -3813, -3814, -3815 (CVE-2026-45829/-45830/-45831/-45833) | none | Transitive dependency of `crewai`. All four concern the **Chroma HTTP server API** (tenants/collections endpoints, RBAC provider). The app never imports chromadb, never starts a Chroma server and does not enable crewai memory or knowledge features |

## npm (production dependencies)

`npm audit --omit=dev`: **0 vulnerabilities.**

## Container images (Trivy, HIGH/CRITICAL)

| Image | Fixable | Without a fix | Notes |
| --- | --- | --- | --- |
| `decisionops-app:local` (Debian 13.7, `python:3.12-slim`) | **0** | 51 Debian HIGH (util-linux family, perl, curl, ncurses, systemd libs, acl), 4 chromadb (above) | Debian has not released fixes; rebuild picks them up when it does. `apt-get upgrade` would not help (no fixed packages) |
| `decisionops-web:local` (Alpine 3.23.6, Caddy 2.11.7) | 3 (excepted) | 0 | CVE-2026-78667, CVE-2026-78669, CVE-2026-97031: Go stdlib / `x/net` compiled into the **official** Caddy 2.11.7 binary (Go 1.26.8). Fixed in Go 1.26.9; clears with the next Caddy release. Locally Caddy listens on 127.0.0.1 only. Recorded in `.trivyignore.yaml` with `expired_at: 2026-12-31` so the check fails again if still present |

## Secrets

gitleaks over the files git would see (tracked + untracked, minus `.gitignore`): **no leaks found.**
