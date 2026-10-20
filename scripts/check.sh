#!/usr/bin/env sh
# Checks runner (plan §17.4): lint, types, unit + integration tests, API-contract freshness and security scans.
# Every step runs even if an earlier one fails; a summary is printed and the exit code is 1 if any step failed.
# Needs Docker and Node/npm. Backend tooling runs in the test image; Postgres is a throwaway container on a
# private network (no published port, removed at exit). Network access is needed for the audit/scan steps.
#
# Usage: scripts/check.sh [--e2e] [--skip-security]
#   --e2e            also run Playwright against the isolated E2E stack (E2E_SETUP_TOKEN must be set; see docs/testing/README.md)
#   --skip-security  skip gitleaks, pip-audit, npm audit and Trivy (e.g. offline)
set -u

ROOT=$(cd "$(dirname "$0")/.." && pwd)
E2E=0
SECURITY=1
for arg in "$@"; do
  case $arg in
    --e2e) E2E=1 ;;
    --skip-security) SECURITY=0 ;;
    *) echo "usage: $0 [--e2e] [--skip-security]" >&2; exit 2 ;;
  esac
done
export MSYS_NO_PATHCONV=1 # Git Bash on Windows: keep container paths as written...

TEST_IMAGE=decisionops-backend-test
PG_IMAGE=pgvector/pgvector:0.8.7-pg18
GITLEAKS_IMAGE=zricethezav/gitleaks:v8.29.1
TAG=check-$$
TMP=$(mktemp -d)
if command -v cygpath >/dev/null 2>&1; then # ...so host paths must be given to docker in Windows form
  ROOT=$(cygpath -m "$ROOT"); TMP=$(cygpath -m "$TMP")
fi
RESULTS=""
FAILED=0

cleanup() {
  docker rm -f "$TAG-db" >/dev/null 2>&1
  docker network rm "$TAG" >/dev/null 2>&1
  rm -rf "$TMP"
}
trap cleanup EXIT INT TERM

step() { # step <name> <command...>
  name=$1; shift
  echo; echo "==> $name"
  if "$@"; then RESULTS="$RESULTS\nPASS  $name"
  else RESULTS="$RESULTS\nFAIL  $name"; FAILED=1; fi
}

build_test_image() { docker build -q -f "$ROOT/backend/Dockerfile" --target test -t "$TEST_IMAGE" "$ROOT" >/dev/null; }
ruff() { docker run --rm "$TEST_IMAGE" python -m ruff check app tests; }

pytest_with_db() {
  docker network create "$TAG" >/dev/null || return 1
  docker run -d --name "$TAG-db" --network "$TAG" -e POSTGRES_USER=decisionops -e POSTGRES_PASSWORD=check \
    "$PG_IMAGE" >/dev/null || return 1
  i=0
  until docker exec "$TAG-db" pg_isready -U decisionops -h 127.0.0.1 >/dev/null 2>&1; do
    i=$((i + 1)); [ $i -gt 60 ] && { echo "Postgres did not become ready"; return 1; }; sleep 1
  done
  docker run --rm --network "$TAG" -e TEST_ADMIN_URL="postgresql://decisionops:check@$TAG-db:5432/postgres" \
    "$TEST_IMAGE" python -m pytest -p no:warnings -q tests
}

npm_deps() { [ -d "$ROOT/frontend/node_modules" ] || (cd "$ROOT/frontend" && npm ci --no-audit --no-fund); }
tsc() { (cd "$ROOT/frontend" && npx tsc -b); }
vitest() { (cd "$ROOT/frontend" && npx vitest run); }

# The committed OpenAPI document and the generated TS schema must match what the current backend produces.
openapi_fresh() {
  docker run --rm "$TEST_IMAGE" python -m app.cli openapi > "$TMP/openapi.json" || return 1
  (cd "$ROOT/frontend" && npx openapi-typescript "$TMP/openapi.json" -o "$TMP/schema.d.ts" \
    --default-non-nullable false >/dev/null 2>&1) || return 1
  ok=0
  cmp -s "$TMP/openapi.json" "$ROOT/frontend/openapi.json" || { echo "frontend/openapi.json is stale"; ok=1; }
  cmp -s "$TMP/schema.d.ts" "$ROOT/frontend/src/api/schema.d.ts" || { echo "frontend/src/api/schema.d.ts is stale"; ok=1; }
  [ $ok -eq 0 ] || echo "Regenerate: python -m app.cli openapi > frontend/openapi.json && (cd frontend && npm run gen:api)"
  return $ok
}

# Scan exactly what git would see (tracked + untracked, minus .gitignore), so local .env files are not reported.
gitleaks() {
  mkdir -p "$TMP/tree"
  (cd "$ROOT" && git ls-files -z --cached --others --exclude-standard | xargs -0 tar -cf - 2>/dev/null) \
    | tar -xf - -C "$TMP/tree" || return 1
  cp "$ROOT/.gitleaks.toml" "$TMP/gitleaks.toml"
  docker run --rm -v "$TMP:/scan" "$GITLEAKS_IMAGE" dir /scan/tree --config /scan/gitleaks.toml --redact --no-banner
}
# Reviewed exceptions (docs/security/dependency-findings.md), all pulled in by crewai 1.15.28 (latest; pins
# mcp<1.29) with no usable fix: the mcp advisory affects only Streamable-HTTP servers (this app uses stdio);
# the chromadb ones affect only the Chroma HTTP server API (never started or imported by this app).
PIP_AUDIT_IGNORE="GHSA-84m7-p3x7-pcfv PYSEC-2026-311 PYSEC-2026-3813 PYSEC-2026-3814 PYSEC-2026-3815"
pip_audit() {
  ignores=""
  for id in $PIP_AUDIT_IGNORE; do ignores="$ignores --ignore-vuln $id"; done
  docker run --rm "$TEST_IMAGE" sh -c \
    "uv export --frozen --no-dev --extra embeddings --no-hashes --no-emit-project -q > /tmp/req.txt && pip-audit --strict -r /tmp/req.txt --disable-pip --no-deps $ignores"
}
npm_audit() { (cd "$ROOT/frontend" && npm audit --omit=dev); }
# Fails only on HIGH/CRITICAL findings that have a fixed version available and are not a reviewed, unexpired
# exception in .trivyignore.yaml; all findings are listed.
trivy_images() {
  command -v trivy >/dev/null || { echo "trivy not installed"; return 1; }
  rc=0
  for img in decisionops-app:local decisionops-web:local; do
    docker image inspect "$img" >/dev/null 2>&1 || { echo "$img not built (docker compose build)"; rc=1; continue; }
    trivy image -q --scanners vuln --severity HIGH,CRITICAL --table-mode detailed "$img" || rc=1
    trivy image -q --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --ignorefile "$ROOT/.trivyignore.yaml" \
      --exit-code 1 --table-mode summary "$img" >/dev/null || { echo "$img: fixable HIGH/CRITICAL findings"; rc=1; }
  done
  return $rc
}
e2e() { (cd "$ROOT/frontend" && npx playwright test); }

step "build test image" build_test_image
step "ruff" ruff
step "pytest (throwaway Postgres)" pytest_with_db
step "npm dependencies" npm_deps
step "tsc -b" tsc
step "vitest" vitest
step "OpenAPI + TS schema fresh" openapi_fresh
if [ $SECURITY -eq 1 ]; then
  step "gitleaks" gitleaks
  step "pip-audit" pip_audit
  step "npm audit --omit=dev" npm_audit
  step "trivy (HIGH/CRITICAL, fixable)" trivy_images
fi
[ $E2E -eq 1 ] && step "playwright e2e" e2e

echo; echo "Summary:"; printf "$RESULTS\n"
exit $FAILED
