# Evaluator — Auth: Google OAuth + httpOnly-Cookie Sessions

Checklist for the Google OAuth + cookie feature. Each item ✅/❌. All ❌ fixed
before done. Pass threshold: ≥ 9.5/10 (≥ 38/40 checks).

## DB migration (5)
- [ ] D1. `password_hash` is now nullable.
- [ ] D2. `auth_provider TEXT NOT NULL DEFAULT 'local'` added (idempotent).
- [ ] D3. `google_sub` column + partial unique index `WHERE google_sub IS NOT NULL`.
- [ ] D4. CHECK `password_hash IS NOT NULL OR google_sub IS NOT NULL` (guarded against duplicate_object).
- [ ] D5. Migration is idempotent — re-running startup on an existing DB does not error.

## Cookies & session (8)
- [ ] C1. `set_auth_cookies` sets access cookie httpOnly, path `/`, max_age = access TTL.
- [ ] C2. Refresh cookie httpOnly, path `/auth/refresh`, max_age = refresh TTL.
- [ ] C3. `secure`/`samesite` driven by `COOKIE_SECURE`/`COOKIE_SAMESITE` env.
- [ ] C4. `clear_auth_cookies` deletes both with matching paths.
- [ ] C5. `/auth/login` sets cookies AND still returns body `TokenResponse`.
- [ ] C6. `/auth/refresh` reads refresh token from body OR cookie, rotates, re-sets cookies.
- [ ] C7. `POST /auth/logout` clears cookies, returns 204.
- [ ] C8. `get_current_user` resolves Bearer header first, then `access_token` cookie; 401 if neither.

## Google OAuth flow (10)
- [ ] G1. `GET /auth/google/login` sets `oauth_state` httpOnly cookie + 302 to Google with correct scope/params.
- [ ] G2. `/auth/google/login` is rate-limited.
- [ ] G3. Callback validates `state` against cookie; mismatch → 400/redirect with error; cookie cleared.
- [ ] G4. Code exchanged at Google token endpoint via httpx (client_secret server-side only).
- [ ] G5. `id_token` verified via `google-auth` with `audience=GOOGLE_CLIENT_ID`.
- [ ] G6. `email_verified` false → redirect `…/login?error=email_unverified`, no cookies.
- [ ] G7. New Google user auto-created: `password_hash NULL`, `auth_provider='google'`, `role='client'`.
- [ ] G8. Existing local account with same verified email → linked (google_sub set, password preserved, role kept).
- [ ] G9. Re-login with same Google account → no duplicate user row.
- [ ] G10. Inactive user → blocked at callback (no cookies set).

## Security (8)
- [ ] S1. OAuth never assigns admin/ops.
- [ ] S2. `state` CSRF defense present + single-use.
- [ ] S3. Redirect target restricted (no open redirect; relative/whitelisted only).
- [ ] S4. `code`, `id_token`, and tokens are never logged.
- [ ] S5. `client_secret` only read server-side, never returned/exposed.
- [ ] S6. Inactive users rejected in `get_current_user` and `/auth/refresh`.
- [ ] S7. DocsAuthMiddleware reads cookie OR header; still admin-only.
- [ ] S8. Existing email/password login + register behavior unchanged.

## Config & dependencies (4)
- [ ] F1. `google-auth>=2.0.0` in requirements.txt.
- [ ] F2. `GOOGLE_CLIENT_ID/SECRET`, `GOOGLE_REDIRECT_URI`, `FRONTEND_URL`, `COOKIE_SECURE`, `COOKIE_SAMESITE` in .env.example + docker-compose backend env.
- [ ] F3. `frontend/next.config.mjs` rewrites `/api/:path*` → backend.
- [ ] F4. Frontend: login page (Google + email/password), AuthContext, all fetches `credentials:"include"`.

## Tests & quality (5)
- [ ] T1. `backend/tests/test_auth_google.py` covers upsert/link/email-unverified/invalid-state (monkeypatch verify + httpx).
- [ ] T2. Cookie-or-header resolution tested (security).
- [ ] T3. Cookie-based docs auth tested (middleware).
- [ ] T4. New db.py functions tested.
- [ ] T5. ruff + mypy clean; full pytest suite green.
