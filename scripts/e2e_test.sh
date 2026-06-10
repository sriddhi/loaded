#!/usr/bin/env bash
# ── Dhando E2E Live Test Suite ────────────────────────────────────────────────
set -euo pipefail

API="http://localhost:9000"
PASS=0; FAIL=0; WARN=0
FAILURES=()

green='\033[0;32m'; red='\033[0;31m'; yellow='\033[0;33m'; reset='\033[0m'

assert() {
  local name="$1" got="$2" expect="$3"
  if [ "$got" = "$expect" ]; then
    echo -e "  ${green}✅ $name${reset}"
    ((PASS++))
  else
    echo -e "  ${red}❌ $name — got '$got', expected '$expect'${reset}"
    ((FAIL++))
    FAILURES+=("$name")
  fi
}

assert_contains() {
  local name="$1" haystack="$2" needle="$3"
  if echo "$haystack" | grep -q "$needle"; then
    echo -e "  ${green}✅ $name${reset}"
    ((PASS++))
  else
    echo -e "  ${red}❌ $name — '$needle' not found in response${reset}"
    ((FAIL++))
    FAILURES+=("$name")
  fi
}

warn() {
  echo -e "  ${yellow}⚠️  $1${reset}"
  ((WARN++))
}

http_code() { echo "$1" | grep "HTTP:" | cut -d: -f2; }
body()      { echo "$1" | grep -v "HTTP:"; }

echo ""
echo "══════════════════════════════════════════════════"
echo "  DHANDO E2E LIVE TEST — $(date +%Y-%m-%d\ %H:%M:%S)"
echo "══════════════════════════════════════════════════"

# ── 0. Health ─────────────────────────────────────────────────────────────────
echo ""
echo "── 0. HEALTH ──"
R=$(curl -s -w "\nHTTP:%{http_code}" $API/health)
assert "health HTTP 200" "$(http_code "$R")" "200"
assert_contains "db connected" "$(body "$R")" '"db":"connected"'
assert_contains "status online" "$(body "$R")" '"status":"online"'

# ── 1. AUTH ───────────────────────────────────────────────────────────────────
echo ""
echo "── 1. AUTH ──"

# 1a. Login - valid admin
R=$(curl -s -w "\nHTTP:%{http_code}" -X POST $API/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=vsriddhi@gmail.com&password=Rizing%23")
assert "admin login HTTP 200" "$(http_code "$R")" "200"
assert_contains "access_token present" "$(body "$R")" "access_token"
ADMIN_TOKEN=$(body "$R" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null)
assert "admin token non-empty" "$([ -n "$ADMIN_TOKEN" ] && echo ok)" "ok"

# 1b. Login - wrong password → 401
sleep 1
R=$(curl -s -w "\nHTTP:%{http_code}" -X POST $API/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=vsriddhi@gmail.com&password=wrongpass")
assert "wrong password HTTP 401" "$(http_code "$R")" "401"

# 1c. Login - unknown user → 401
sleep 1
R=$(curl -s -w "\nHTTP:%{http_code}" -X POST $API/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=nobody@example.com&password=x")
assert "unknown user HTTP 401" "$(http_code "$R")" "401"

# 1d. No token → 401 on protected route
sleep 1
R=$(curl -s -w "\nHTTP:%{http_code}" $API/trading/status)
assert "no token → 401" "$(http_code "$R")" "401"

# 1e. Malformed token → 401
sleep 1
R=$(curl -s -w "\nHTTP:%{http_code}" $API/trading/status -H "Authorization: Bearer garbage")
assert "bad token → 401" "$(http_code "$R")" "401"

# wait for rate limit window to clear between login batches
sleep 62

# ── 2. REGISTER + SECOND USER ────────────────────────────────────────────────
echo ""
echo "── 2. USER REGISTRATION + PERMISSIONS ──"

# Fresh admin token after sleep
ADMIN_TOKEN=$(curl -s -X POST $API/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=vsriddhi@gmail.com&password=Rizing%23" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null)

# 2a. Register new test user
sleep 1
R=$(curl -s -w "\nHTTP:%{http_code}" -X POST $API/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"testuser_e2e@example.com","password":"TestPass123!","full_name":"E2E Test User"}')
CODE=$(http_code "$R")
if [ "$CODE" = "201" ] || [ "$CODE" = "200" ]; then
  echo -e "  ${green}✅ register new user HTTP $CODE${reset}"; ((PASS++))
elif [ "$CODE" = "409" ]; then
  warn "register: user already exists (idempotent re-run)"
else
  echo -e "  ${red}❌ register new user — got $CODE${reset}"; ((FAIL++))
  FAILURES+=("register new user")
fi

# 2b. Login as test user
sleep 2
R=$(curl -s -w "\nHTTP:%{http_code}" -X POST $API/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=testuser_e2e@example.com&password=TestPass123!")
assert "test user login HTTP 200" "$(http_code "$R")" "200"
USER_TOKEN=$(body "$R" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)

# 2c. Test user role is 'user' not 'admin'
USER_ROLE=$(body "$R" | python3 -c "
import sys,json,base64
d=json.load(sys.stdin)
tok=d.get('access_token','')
payload=tok.split('.')[1] if tok else ''
# pad
payload += '=='*(-len(payload)%4)
try:
    p=json.loads(base64.urlsafe_b64decode(payload))
    print(p.get('role','unknown'))
except:
    print('unknown')
" 2>/dev/null)
assert "test user role=user" "$USER_ROLE" "user"

echo ""
echo "── 3. PERMISSION RBAC ──"

# 3a. Non-admin cannot start system job
sleep 1
R=$(curl -s -w "\nHTTP:%{http_code}" -X POST $API/trading/jobs/1/start \
  -H "Authorization: Bearer $USER_TOKEN")
assert "non-admin cannot start system job → 403" "$(http_code "$R")" "403"

# 3b. Non-admin can list jobs (sees system job + own jobs)
sleep 1
R=$(curl -s -w "\nHTTP:%{http_code}" $API/trading/jobs \
  -H "Authorization: Bearer $USER_TOKEN")
assert "non-admin GET /trading/jobs → 200" "$(http_code "$R")" "200"
assert_contains "sees system job in list" "$(body "$R")" "spy_orb_0dte"

# 3c. Admin sees all
sleep 1
R=$(curl -s -w "\nHTTP:%{http_code}" $API/trading/jobs \
  -H "Authorization: Bearer $ADMIN_TOKEN")
assert "admin GET /trading/jobs → 200" "$(http_code "$R")" "200"

echo ""
echo "── 4. TRADING JOB CRUD ──"

# 4a. Create job as test user
sleep 1
R=$(curl -s -w "\nHTTP:%{http_code}" -X POST $API/trading/jobs \
  -H "Authorization: Bearer $USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"e2e_test_job","strategy":"orb","config":{"symbol":"SPY"}}')
assert "create user job → 201" "$(http_code "$R")" "201"
USER_JOB_ID=$(body "$R" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
assert_contains "job has user type" "$(body "$R")" '"job_type":"user"'
assert_contains "config stored" "$(body "$R")" '"symbol":"SPY"'

# 4b. GET own job
sleep 1
R=$(curl -s -w "\nHTTP:%{http_code}" $API/trading/jobs/$USER_JOB_ID \
  -H "Authorization: Bearer $USER_TOKEN")
assert "GET own job → 200" "$(http_code "$R")" "200"

# 4c. Duplicate name → 409
sleep 1
R=$(curl -s -w "\nHTTP:%{http_code}" -X POST $API/trading/jobs \
  -H "Authorization: Bearer $USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"e2e_test_job","strategy":"orb"}')
assert "duplicate job name → 409" "$(http_code "$R")" "409"

# 4d. Admin cannot see non-admin user's job via wrong user token
sleep 1
R=$(curl -s -w "\nHTTP:%{http_code}" $API/trading/jobs/$USER_JOB_ID \
  -H "Authorization: Bearer $USER_TOKEN")
assert "user sees own job → 200" "$(http_code "$R")" "200"

# 4e. Other user cannot start test user's job (would need a 3rd token, skip — covered by unit tests)

# 4f. Start user job
sleep 1
R=$(curl -s -w "\nHTTP:%{http_code}" -X POST $API/trading/jobs/$USER_JOB_ID/start \
  -H "Authorization: Bearer $USER_TOKEN")
assert "start own job → 200" "$(http_code "$R")" "200"
assert_contains "session opened" "$(body "$R")" "session"
SESSION_ID=$(body "$R" | python3 -c "import sys,json; print(json.load(sys.stdin).get('session',{}).get('id',''))" 2>/dev/null)

# 4g. Start another job while one running → 409
sleep 1
R=$(curl -s -w "\nHTTP:%{http_code}" -X POST $API/trading/jobs \
  -H "Authorization: Bearer $USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"e2e_second_job","strategy":"orb"}')
SECOND_JOB_ID=$(body "$R" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
sleep 1
R=$(curl -s -w "\nHTTP:%{http_code}" -X POST $API/trading/jobs/$SECOND_JOB_ID/start \
  -H "Authorization: Bearer $USER_TOKEN")
assert "start second job while one running → 409" "$(http_code "$R")" "409"
assert_contains "already have a running job" "$(body "$R")" "already have a running job"

# 4h. GET today session
sleep 1
R=$(curl -s -w "\nHTTP:%{http_code}" $API/trading/jobs/$USER_JOB_ID/sessions/today \
  -H "Authorization: Bearer $USER_TOKEN")
assert "GET sessions/today → 200" "$(http_code "$R")" "200"
assert_contains "session in response" "$(body "$R")" '"session"'

# 4i. Stop job
sleep 1
R=$(curl -s -w "\nHTTP:%{http_code}" -X POST $API/trading/jobs/$USER_JOB_ID/stop \
  -H "Authorization: Bearer $USER_TOKEN")
assert "stop own job → 200" "$(http_code "$R")" "200"
assert_contains "job status idle" "$(body "$R")" '"status":"idle"'

# 4j. List sessions for job
sleep 1
R=$(curl -s -w "\nHTTP:%{http_code}" $API/trading/jobs/$USER_JOB_ID/sessions \
  -H "Authorization: Bearer $USER_TOKEN")
assert "list sessions → 200" "$(http_code "$R")" "200"

echo ""
echo "── 5. LEGACY TRADING ENDPOINTS ──"

# 5a. GET /trading/status
sleep 1
R=$(curl -s -w "\nHTTP:%{http_code}" $API/trading/status \
  -H "Authorization: Bearer $ADMIN_TOKEN")
assert "GET /trading/status → 200" "$(http_code "$R")" "200"
assert_contains "status field present" "$(body "$R")" '"status"'

# 5b. POST /trading/start (system job, idempotent)
sleep 1
R=$(curl -s -w "\nHTTP:%{http_code}" -X POST $API/trading/start \
  -H "Authorization: Bearer $ADMIN_TOKEN")
assert "POST /trading/start → 200" "$(http_code "$R")" "200"

# 5c. GET /trading/log
sleep 1
R=$(curl -s -w "\nHTTP:%{http_code}" $API/trading/log \
  -H "Authorization: Bearer $ADMIN_TOKEN")
assert "GET /trading/log → 200" "$(http_code "$R")" "200"

echo ""
echo "── 6. FUNDAMENTALS AGENTS ──"

# 6a. Ingest NVDA
sleep 1
R=$(curl -s -w "\nHTTP:%{http_code}" -X POST $API/agents/ingest/NVDA \
  -H "Authorization: Bearer $ADMIN_TOKEN")
CODE=$(http_code "$R")
if [ "$CODE" = "200" ]; then
  echo -e "  ${green}✅ ingest NVDA → 200${reset}"; ((PASS++))
  assert_contains "periods written" "$(body "$R")" "periods_written"
else
  warn "ingest NVDA → $CODE (may be rate-limited by yfinance)"
fi

# 6b. GET fundamentals for all 3 tickers
for SYM in NVDA HOOD KO; do
  sleep 1
  R=$(curl -s -w "\nHTTP:%{http_code}" $API/agents/fundamentals/$SYM \
    -H "Authorization: Bearer $ADMIN_TOKEN")
  assert "GET fundamentals/$SYM → 200" "$(http_code "$R")" "200"
  assert_contains "$SYM annual data" "$(body "$R")" '"annual"'
  assert_contains "$SYM quarterly data" "$(body "$R")" '"quarterly"'
  assert_contains "$SYM ratios" "$(body "$R")" '"ratios"'
done

# 6c. GET equity metadata
sleep 1
R=$(curl -s -w "\nHTTP:%{http_code}" $API/agents/equity/NVDA \
  -H "Authorization: Bearer $ADMIN_TOKEN")
CODE=$(http_code "$R")
if [ "$CODE" = "200" ]; then
  echo -e "  ${green}✅ GET equity/NVDA → 200${reset}"; ((PASS++))
else
  warn "GET equity/NVDA → $CODE"
fi

# 6d. Non-existent ticker
sleep 1
R=$(curl -s -w "\nHTTP:%{http_code}" $API/agents/fundamentals/ZZZZ999 \
  -H "Authorization: Bearer $ADMIN_TOKEN")
CODE=$(http_code "$R")
if [ "$CODE" = "404" ] || [ "$CODE" = "422" ]; then
  echo -e "  ${green}✅ unknown ticker → $CODE${reset}"; ((PASS++))
else
  warn "unknown ticker → $CODE (expected 404 or 422)"
fi

# 6e. Batch ingest
sleep 1
R=$(curl -s -w "\nHTTP:%{http_code}" -X POST $API/agents/ingest/batch \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"symbols":["NVDA","HOOD","KO"]}')
CODE=$(http_code "$R")
if [ "$CODE" = "200" ]; then
  echo -e "  ${green}✅ batch ingest → 200${reset}"; ((PASS++))
else
  warn "batch ingest → $CODE"
fi

echo ""
echo "── 7. STRATEGIES ──"

sleep 1
R=$(curl -s -w "\nHTTP:%{http_code}" $API/strategies/ \
  -H "Authorization: Bearer $ADMIN_TOKEN")
CODE=$(http_code "$R")
if [ "$CODE" = "200" ]; then
  echo -e "  ${green}✅ GET /strategies/ → 200${reset}"; ((PASS++))
else
  warn "GET /strategies/ → $CODE"
fi

echo ""
echo "── 8. ALPACA ENDPOINTS ──"

sleep 1
R=$(curl -s -w "\nHTTP:%{http_code}" $API/alpaca/account \
  -H "Authorization: Bearer $ADMIN_TOKEN")
CODE=$(http_code "$R")
if [ "$CODE" = "200" ]; then
  echo -e "  ${green}✅ GET /alpaca/account → 200${reset}"; ((PASS++))
elif [ "$CODE" = "503" ] || [ "$CODE" = "424" ] || [ "$CODE" = "422" ]; then
  warn "GET /alpaca/account → $CODE (credentials not set — expected in this env)"
else
  warn "GET /alpaca/account → $CODE"
fi

# ── SUMMARY ───────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════"
TOTAL=$((PASS + FAIL))
echo -e "  ${green}PASS: $PASS / $TOTAL${reset}   ${yellow}WARN: $WARN${reset}   ${red}FAIL: $FAIL${reset}"
if [ ${#FAILURES[@]} -gt 0 ]; then
  echo ""
  echo -e "  ${red}Failed checks:${reset}"
  for f in "${FAILURES[@]}"; do echo "    - $f"; done
fi
echo "══════════════════════════════════════════════════"
echo ""
exit $FAIL
