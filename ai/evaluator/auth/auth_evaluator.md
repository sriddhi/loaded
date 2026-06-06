# Evaluator: Authentication & User Management

## Scoring
- Each check is worth 1 point
- Total: 50 checks
- Pass threshold: **9.5 / 10** (≥ 47 / 50 checks must pass)
- Score = passing_checks / 50 × 10

---

## 1. File Structure (5 checks)
- [ ] `backend/app/auth/__init__.py` exists
- [ ] `backend/app/auth/models.py` exists
- [ ] `backend/app/auth/db.py` exists
- [ ] `backend/app/auth/security.py` exists
- [ ] `backend/app/auth/router.py` exists
- [ ] `backend/app/auth/middleware.py` exists
- [ ] `backend/tests/test_auth_router.py` exists
- [ ] `backend/tests/test_auth_security.py` exists
- [ ] `backend/tests/test_auth_db.py` exists
- [ ] `scripts/seed_admin.py` exists

## 2. Dependencies (3 checks)
- [ ] `passlib[bcrypt]` in `requirements.txt`
- [ ] `python-jose[cryptography]` in `requirements.txt`
- [ ] `slowapi` in `requirements.txt`

## 3. Environment (3 checks)
- [ ] `JWT_SECRET_KEY` in `.env.example`
- [ ] `ADMIN_EMAIL` in `.env.example`
- [ ] `ADMIN_PASSWORD` in `.env.example`

## 4. Database Migration (2 checks)
- [ ] `user_role` ENUM type created with `admin`, `client`, `ops` values
- [ ] `users` table created with `id`, `email`, `password_hash`, `role`, `is_active`, `created_at`

## 5. Security Module (6 checks)
- [ ] `hash_password` uses bcrypt
- [ ] `verify_password` uses `pwd_context.verify`
- [ ] `create_access_token` sets `exp`, `sub`, `role`, `type=access`
- [ ] `create_refresh_token` sets `exp`, `sub`, `type=refresh`
- [ ] `decode_token` raises HTTP 401 on `JWTError`
- [ ] `get_current_user` dependency raises 401 for inactive users

## 6. Auth Router Endpoints (6 checks)
- [ ] `POST /auth/register` — public, creates user, returns `UserOut` (no password field)
- [ ] `POST /auth/login` — public, OAuth2 form, returns `TokenResponse`
- [ ] `POST /auth/refresh` — public, accepts refresh token, returns new access token
- [ ] `GET /auth/me` — requires auth, returns calling user
- [ ] `GET /auth/users` — requires admin role
- [ ] `PATCH /auth/users/{user_id}` — requires admin role

## 7. Route Protection (5 checks)
- [ ] All non-auth routers mounted with `dependencies=[Depends(get_current_user)]`
- [ ] `/docs` returns 401 without token
- [ ] `/docs` returns 403 with non-admin token
- [ ] `/redoc` returns 401 without token
- [ ] `/openapi.json` returns 401 without token

## 8. Security Constraints (6 checks)
- [ ] Passwords never present in any response model
- [ ] Duplicate email registration returns 409
- [ ] Wrong password login returns 401
- [ ] Inactive user login returns 401
- [ ] Non-admin cannot register with role `admin` or `ops`
- [ ] Login endpoint decorated with `@limiter.limit("5/minute")`

## 9. Test Coverage (8 checks)
- [ ] `test_auth_router.py` has ≥ 15 test functions
- [ ] `test_auth_security.py` has ≥ 6 test functions
- [ ] `test_auth_db.py` has ≥ 4 test functions
- [ ] Register success test
- [ ] Login success + token returned test
- [ ] `/auth/me` with no token → 401 test
- [ ] Admin-only endpoint with non-admin → 403 test
- [ ] Refresh token success test

## 10. Code Quality (6 checks)
- [ ] `mypy` passes with no errors on `app/auth/`
- [ ] `ruff lint` passes on `app/auth/`
- [ ] `ruff format` passes on `app/auth/`
- [ ] All tests pass (`pytest`)
- [ ] No hardcoded secrets (JWT secret always from `os.getenv`)
- [ ] Startup raises clear error if `JWT_SECRET_KEY` is not set
