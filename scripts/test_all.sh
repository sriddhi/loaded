#!/usr/bin/env bash
# test_all.sh — start the app and run all tests (unit + live smoke)
# Usage: ./scripts/test_all.sh

set -euo pipefail

BASE="http://localhost:8000"
PASS=0
FAIL=0

# ── helpers ────────────────────────────────────────────────────────────────────

green()  { echo -e "\033[32m✅  $*\033[0m"; }
red()    { echo -e "\033[31m❌  $*\033[0m"; }
header() { echo -e "\n\033[1;34m── $* ──\033[0m"; }

check() {
  local label="$1" expected="$2" actual="$3"
  if [ "$actual" = "$expected" ]; then
    green "$label"
    ((PASS++)) || true
  else
    red "$label (expected $expected, got $actual)"
    ((FAIL++)) || true
  fi
}

# ── 1. unit tests ──────────────────────────────────────────────────────────────

header "Unit tests (pytest)"
cd "$(dirname "$0")/../backend"
source .venv/bin/activate
pytest -q --tb=short
green "All unit tests passed"
cd - > /dev/null

# ── 2. ensure app is running ───────────────────────────────────────────────────

header "Starting app"
cd "$(dirname "$0")/.."
docker compose up -d > /dev/null 2>&1

echo "Waiting for backend..."
for i in $(seq 1 20); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/health" 2>/dev/null || true)
  if [ "$STATUS" = "200" ]; then
    green "Backend is up"
    break
  fi
  sleep 1
  if [ "$i" = "20" ]; then
    red "Backend did not start in time"
    docker compose logs --tail=20 backend
    exit 1
  fi
done

# ── 3. health ──────────────────────────────────────────────────────────────────

header "Smoke: /health"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/health")
check "/health returns 200" "200" "$STATUS"

# ── 4. auth — public endpoints ────────────────────────────────────────────────

header "Smoke: Auth endpoints"

# Register a test user
REG=$(curl -s -X POST "$BASE/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"email":"smoketest@loaded.app","password":"smokepass1"}')
REG_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"email":"smoketest2@loaded.app","password":"smokepass1"}')
check "POST /auth/register → 201" "201" "$REG_STATUS"

# Login
LOGIN=$(curl -s -X POST "$BASE/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=smoketest2@loaded.app&password=smokepass1")
TOKEN=$(echo "$LOGIN" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('access_token',''))" 2>/dev/null || true)
LOGIN_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=smoketest2@loaded.app&password=smokepass1")
check "POST /auth/login → 200" "200" "$LOGIN_STATUS"

# Login with wrong password
WRONG=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=smoketest2@loaded.app&password=wrongpassword")
check "POST /auth/login wrong password → 401" "401" "$WRONG"

# /auth/me without token
NO_TOKEN=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/auth/me")
check "GET /auth/me no token → 401" "401" "$NO_TOKEN"

# /auth/me with valid token
ME_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/auth/me" \
  -H "Authorization: Bearer $TOKEN")
check "GET /auth/me with token → 200" "200" "$ME_STATUS"

# Duplicate email → 409
DUP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"email":"smoketest2@loaded.app","password":"smokepass1"}')
check "POST /auth/register duplicate → 409" "409" "$DUP"

# ── 5. protected routes ────────────────────────────────────────────────────────

header "Smoke: Protected routes"

# Strategies without token
STRAT_NO_AUTH=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/strategies/")
check "GET /strategies/ no token → 401" "401" "$STRAT_NO_AUTH"

# Strategies with token
STRAT_AUTH=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/strategies/" \
  -H "Authorization: Bearer $TOKEN")
check "GET /strategies/ with token → 200" "200" "$STRAT_AUTH"

# Market data without token
MD_NO_AUTH=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/marketdata/stocks/AAPL/snapshot")
check "GET /marketdata/... no token → 401" "401" "$MD_NO_AUTH"

# ── 6. docs protection ────────────────────────────────────────────────────────

header "Smoke: Docs protection"

DOCS_NO_TOKEN=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/docs")
check "GET /docs no token → 401" "401" "$DOCS_NO_TOKEN"

DOCS_USER_TOKEN=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/docs" \
  -H "Authorization: Bearer $TOKEN")
check "GET /docs non-admin token → 403" "403" "$DOCS_USER_TOKEN"

OPENAPI_NO_TOKEN=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/openapi.json")
check "GET /openapi.json no token → 401" "401" "$OPENAPI_NO_TOKEN"

# ── 7. summary ────────────────────────────────────────────────────────────────

header "Results"
TOTAL=$((PASS + FAIL))
echo "  Unit tests:  ✅ passed"
echo "  Smoke tests: $PASS/$TOTAL passed"

if [ "$FAIL" -gt 0 ]; then
  red "$FAIL smoke test(s) failed"
  exit 1
else
  green "All $TOTAL smoke tests passed"
fi
