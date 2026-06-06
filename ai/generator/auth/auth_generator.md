# Generator: Authentication & User Management

## Feature
Full JWT-based authentication with role-based access control (RBAC). All API routes, Swagger docs, and OpenAPI schema are protected. No unauthenticated access to any internal surface.

---

## Scope

### New files
- `backend/app/auth/__init__.py`
- `backend/app/auth/models.py` — Pydantic request/response schemas
- `backend/app/auth/db.py` — raw asyncpg DB helpers (users table CRUD)
- `backend/app/auth/security.py` — password hashing, JWT encode/decode, role dependency
- `backend/app/auth/router.py` — FastAPI router (`/auth`)
- `backend/app/auth/middleware.py` — Swagger/docs route guard
- `backend/tests/test_auth_router.py`
- `backend/tests/test_auth_security.py`
- `backend/tests/test_auth_db.py`
- `scripts/seed_admin.py` — one-shot admin seeder

### Modified files
- `backend/app/main.py` — mount auth router, add docs guard middleware, protect `/docs` `/redoc` `/openapi.json`
- `backend/requirements.txt` — add `passlib[bcrypt]`, `python-jose[cryptography]`, `slowapi`
- `.env.example` — add `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`

---

## Database

Run this migration in `main.py` startup (after existing migrations):

```sql
DO $$ BEGIN
  CREATE TYPE user_role AS ENUM ('admin', 'client', 'ops');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          user_role NOT NULL DEFAULT 'client',
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## Environment Variables

```
JWT_SECRET_KEY=<random 64-char hex>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
ADMIN_EMAIL=admin@loaded.app
ADMIN_PASSWORD=<strong password>
```

---

## Security Module (`auth/security.py`)

### Password hashing
```python
from passlib.context import CryptContext
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(plain: str) -> str: ...
def verify_password(plain: str, hashed: str) -> bool: ...
```

### JWT
```python
from jose import JWTError, jwt

def create_access_token(user_id: int, role: str) -> str:
    # exp = now + ACCESS_TOKEN_EXPIRE_MINUTES
    # payload: {"sub": str(user_id), "role": role, "type": "access"}

def create_refresh_token(user_id: int) -> str:
    # exp = now + REFRESH_TOKEN_EXPIRE_DAYS
    # payload: {"sub": str(user_id), "type": "refresh"}

def decode_token(token: str) -> dict:
    # raises HTTPException 401 on JWTError or expiry
```

### FastAPI dependencies
```python
async def get_current_user(token: str = Depends(oauth2_scheme), db=Depends(get_db)) -> UserRow:
    # decode token, load user from DB, raise 401 if inactive

def require_role(*roles: str):
    # returns a dependency that calls get_current_user then checks role
    # raises 403 if role not in roles
```

Use `OAuth2PasswordBearer(tokenUrl="/auth/login")` as the scheme.

---

## Auth Router (`auth/router.py`)

Prefix: `/auth`, tag: `auth`

### `POST /auth/register`
- **No auth required** (public)
- Body: `{ email, password, role? }` — role defaults to `"client"`; only an existing admin can set role to `"admin"` or `"ops"` (check `Authorization` header if present; if absent, force `"client"`)
- Hash password, insert user, return `UserOut` (no password)
- 409 if email already exists

### `POST /auth/login`
- **No auth required** (public)
- Body: `application/x-www-form-urlencoded` — `username` (email) + `password` (OAuth2 standard)
- Rate limited: 5 requests / 60 seconds per client IP via `slowapi`
- Verify email + password; 401 if wrong
- Return `{ access_token, refresh_token, token_type: "bearer" }`

### `POST /auth/refresh`
- **No auth required** (uses refresh token in body)
- Body: `{ refresh_token: str }`
- Decode refresh token, load user, issue new access token
- 401 if token invalid/expired

### `GET /auth/me`
- **Requires auth** (`get_current_user`)
- Returns `UserOut` for the calling user

### `GET /auth/users`
- **Requires auth** (`require_role("admin")`)
- Returns list of all users (`UserOut`)

### `PATCH /auth/users/{user_id}`
- **Requires auth** (`require_role("admin")`)
- Body: `{ role?, is_active? }` — partial update
- Returns updated `UserOut`

---

## Pydantic Models (`auth/models.py`)

```python
class UserCreate(BaseModel):
    email: EmailStr
    password: str  # min 8 chars
    role: Literal["admin", "client", "ops"] = "client"

class UserOut(BaseModel):
    id: int
    email: EmailStr
    role: str
    is_active: bool
    created_at: datetime

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class UserUpdate(BaseModel):
    role: Literal["admin", "client", "ops"] | None = None
    is_active: bool | None = None
```

---

## Docs / OpenAPI Protection (`auth/middleware.py` + `main.py`)

Protect `/docs`, `/redoc`, `/openapi.json` with admin-only JWT check:

```python
from starlette.middleware.base import BaseHTTPMiddleware

PROTECTED_PATHS = {"/docs", "/redoc", "/openapi.json"}

class DocsAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path in PROTECTED_PATHS:
            token = _extract_bearer(request)
            if not token:
                return Response("Unauthorized", status_code=401)
            try:
                payload = decode_token(token)
                if payload.get("role") != "admin":
                    return Response("Forbidden", status_code=403)
            except Exception:
                return Response("Unauthorized", status_code=401)
        return await call_next(request)
```

Add to `main.py`:
```python
app.add_middleware(DocsAuthMiddleware)
```

Also apply `get_current_user` as a global dependency to all non-auth routes:

```python
app.include_router(auth_router)  # no dependency — auth routes are public
app.include_router(strategies_router, dependencies=[Depends(get_current_user)])
app.include_router(alpaca_router, dependencies=[Depends(get_current_user)])
app.include_router(marketdata_router, dependencies=[Depends(get_current_user)])
```

---

## Rate Limiting (`main.py`)

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

Apply to login only:
```python
@router.post("/login")
@limiter.limit("5/minute")
async def login(request: Request, ...):
```

---

## Admin Seeder (`scripts/seed_admin.py`)

Standalone script (not a FastAPI endpoint):

```python
# Usage: python scripts/seed_admin.py
# Reads DATABASE_URL, ADMIN_EMAIL, ADMIN_PASSWORD from env
# Inserts admin user if email does not already exist
# Prints "Admin created" or "Admin already exists"
```

Also call this automatically from `main.py` lifespan startup if `ADMIN_EMAIL` and `ADMIN_PASSWORD` are set.

---

## Tests

### `test_auth_router.py` (minimum 15 tests)
- Register → 200, user returned without password
- Register duplicate email → 409
- Register with role field absent → defaults to `client`
- Non-admin cannot register with role `admin`
- Login valid credentials → returns access + refresh tokens
- Login wrong password → 401
- Login rate limit → 429 after 5 attempts
- `/auth/me` with valid token → 200
- `/auth/me` with no token → 401
- `/auth/me` with expired token → 401
- `/auth/refresh` with valid refresh token → new access token
- `/auth/refresh` with access token (wrong type) → 401
- Admin `GET /auth/users` → list of users
- Non-admin `GET /auth/users` → 403
- Admin `PATCH /auth/users/{id}` → role/active updated

### `test_auth_security.py` (minimum 6 tests)
- `hash_password` + `verify_password` round-trip
- `verify_password` wrong password → False
- `create_access_token` → decode yields correct sub + role
- `create_refresh_token` → decode yields correct sub + type=refresh
- `decode_token` with tampered token → raises 401
- `decode_token` with expired token → raises 401

### `test_auth_db.py` (minimum 4 tests)
- `create_user` inserts and returns row
- `get_user_by_email` returns None for unknown email
- `update_user` changes role
- Duplicate email raises unique constraint error

---

## Security Checklist (must pass before done)

- [ ] No route outside `/auth/login`, `/auth/register`, `/auth/refresh` is reachable without a valid JWT
- [ ] `/docs`, `/redoc`, `/openapi.json` return 401 without token, 403 for non-admin
- [ ] Passwords never appear in any API response
- [ ] JWT secret read from env — startup fails with clear error if missing
- [ ] Login rate limited to 5/min per IP
- [ ] Inactive users (`is_active=false`) cannot authenticate
- [ ] Role escalation prevented: non-admin cannot self-assign `admin` or `ops`
