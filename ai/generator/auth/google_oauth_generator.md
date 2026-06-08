# Generator — Auth: Google OAuth + httpOnly-Cookie Sessions

**Module:** `auth`
**Feature:** "Sign in with Google" added alongside the existing email/password
auth, with JWT transport moved to httpOnly cookies (backward compatible).
**Additive:** Do NOT modify the locked `auth_generator.md` / `auth_evaluator.md`.

---

## Goal

Add Google as a second login/signup method without removing email/password.
Both methods mint the **same** existing JWTs (`create_access_token` /
`create_refresh_token`). Tokens are delivered as httpOnly cookies; body tokens
are still returned for backward compatibility.

## Decisions (fixed)

- **Flow:** backend **authorization-code redirect** flow. `client_secret` never
  leaves the server. No Google JS SDK on the frontend.
- **Cookies:** httpOnly. Cross-origin (`:3000` vs `:8000`) is solved by a Next.js
  `rewrites()` proxy so the browser is same-origin with the API → `SameSite=Lax`.
  Cookie `Secure`/`SameSite` are env-driven (`COOKIE_SECURE`, `COOKIE_SAMESITE`).
- **Account model:** generic `auth_provider` column (future providers). Google
  login auto-links to an existing local account **only when** Google asserts
  `email_verified=true` for the same email. OAuth-created users are always
  `role='client'`; OAuth never elevates roles.

---

## Build spec

### 1. DB migration — `backend/app/main.py`, appended to `DB_MIGRATIONS` after `CREATE TABLE users`
Idempotent (the table uses `CREATE TABLE IF NOT EXISTS`):
```sql
ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_provider TEXT NOT NULL DEFAULT 'local';
ALTER TABLE users ADD COLUMN IF NOT EXISTS google_sub TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_google_sub ON users (google_sub) WHERE google_sub IS NOT NULL;
DO $$ BEGIN
  ALTER TABLE users ADD CONSTRAINT chk_users_credential
    CHECK (password_hash IS NOT NULL OR google_sub IS NOT NULL);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
```

### 2. `backend/app/auth/security.py`
- `COOKIE_SECURE` (env, default `false`), `COOKIE_SAMESITE` (env, default `lax`),
  `ACCESS_COOKIE = "access_token"`, `REFRESH_COOKIE = "refresh_token"`.
- `set_auth_cookies(response, access, refresh)`:
  - access cookie: `httponly=True`, `samesite=COOKIE_SAMESITE`, `secure=COOKIE_SECURE`,
    `max_age=ACCESS_TOKEN_EXPIRE_MINUTES*60`, `path="/"`.
  - refresh cookie: same flags, `path="/auth/refresh"`, `max_age=REFRESH_TOKEN_EXPIRE_DAYS*86400`.
- `clear_auth_cookies(response)`: delete both with matching `path`.
- Replace `get_current_user(token=Depends(oauth2_scheme))` with a `Request`-based
  resolver: read `Authorization: Bearer` first, then `request.cookies[ACCESS_COOKIE]`;
  401 if neither. Keep behavior (type=="access", DB lookup, is_active) identical.
  `require_role` stays unchanged.

### 3. `backend/app/auth/middleware.py`
- `_extract_bearer`: if no Bearer header, fall back to
  `request.cookies.get("access_token")`. Admin-role check unchanged.

### 4. `backend/app/auth/db.py`
- `get_user_by_google_sub(conn, sub) -> dict|None`
- `create_oauth_user(conn, email, google_sub, role="client") -> dict`
  (INSERT `password_hash=NULL, auth_provider='google', google_sub=$`)
- `link_google_to_user(conn, user_id, google_sub) -> dict`
- Add `auth_provider, google_sub` to existing SELECT column lists.

### 5. `backend/app/auth/router.py`
- `GET /auth/google/login` (rate-limit ~10/min): generate `state =
  secrets.token_urlsafe(32)`; set short-lived httpOnly `oauth_state` cookie
  (max_age 600); 302 → `https://accounts.google.com/o/oauth2/v2/auth` with
  `client_id, redirect_uri=GOOGLE_REDIRECT_URI, response_type=code,
  scope="openid email profile", state, access_type=online, prompt=select_account`.
- `GET /auth/google/callback` (query `code`, `state`, optional `error`):
  1. `error` present → 302 `FRONTEND_URL/login?error=oauth_denied`.
  2. Validate `state` == `oauth_state` cookie (else 400 `invalid_state`); clear cookie.
  3. Exchange `code` at `https://oauth2.googleapis.com/token` via `httpx`.
  4. Verify `id_token` with `google.oauth2.id_token.verify_oauth2_token(...,
     audience=GOOGLE_CLIENT_ID)`. Extract `sub`, `email`, `email_verified`.
  5. `email_verified` not true → 302 `…/login?error=email_unverified`.
  6. Upsert: by `google_sub` → else by email (create if absent; **link** if a
     local account exists). Reject inactive → `…/login?error=inactive`.
  7. `set_auth_cookies`; 302 → `FRONTEND_URL`.
  8. Any unexpected failure → `…/login?error=oauth_failed`. Never log
     `code`/`id_token`/tokens.
- `POST /auth/logout`: `clear_auth_cookies`, 204.
- `POST /auth/login`: also `set_auth_cookies` (still returns `TokenResponse`).
- `POST /auth/refresh`: body optional; fall back to `refresh_token` cookie;
  rotate + `set_auth_cookies` + return body tokens.

### 6. Config
- `backend/requirements.txt`: add `google-auth>=2.0.0`.
- `.env.example` + `docker-compose.yml` backend `environment`: `GOOGLE_CLIENT_ID`,
  `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`,
  `FRONTEND_URL` (default `http://localhost:3000`), `COOKIE_SECURE` (default false),
  `COOKIE_SAMESITE` (default lax).

### 7. Frontend
- `frontend/next.config.mjs`: `async rewrites()` mapping
  `/api/:path*` → `http://backend:8000/:path*`.
- `frontend/src/app/login/page.tsx`: "Continue with Google" link to
  `/api/auth/google/login` + email/password form → `/api/auth/login` and
  `/api/auth/register`, all `fetch(..., { credentials: "include" })`. Design
  system: bg `#0a0a0a`, fg `#f5f5f5`, accent `#e8ff47`, inline styles, mono font.
- `frontend/src/context/AuthContext.tsx` + wrap in `app/layout.tsx`: hydrate via
  `GET /api/auth/me`, expose `user` + `logout()` (POST `/api/auth/logout`).
- Small `apiFetch` helper: always `credentials:"include"`, retry once via
  `/api/auth/refresh` on 401.

## Constraints
- Email/password login + register continue to work unchanged for existing clients.
- Existing Bearer-token clients/tests keep working (header path preserved).
- No secret logging. `client_secret` server-side only.
- ruff + mypy + existing pytest suite stay green.
