import json
import os
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import asyncpg
from app.agents.router import router as agents_router
from app.alpaca.router import router as alpaca_router
from app.alpaca_client import alpaca_ok
from app.auth.middleware import DocsAuthMiddleware
from app.auth.router import router as auth_router
from app.auth.security import get_current_user
from app.marketdata.router import router as marketdata_router
from app.strategies.router import router as strategies_router
from app.trading.router import router as trading_router
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# ── Migrations ─────────────────────────────────────────────────────────────────
# Run in order — extensions first, then reference tables, then dependent tables.

DB_MIGRATIONS = """
-- ── Extensions ──────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS vector;

-- ── Existing tables (auth + strategies) ────────────────────────────────────
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

CREATE TABLE IF NOT EXISTS strategies (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    config_json JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS evaluations (
    id SERIAL PRIMARY KEY,
    strategy_id INTEGER REFERENCES strategies(id),
    symbol TEXT NOT NULL,
    period TEXT NOT NULL,
    metrics_json JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── GICS reference ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS gics_sectors (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS gics_industries (
    code        TEXT PRIMARY KEY,
    sector_code TEXT REFERENCES gics_sectors(code),
    name        TEXT NOT NULL
);

-- ── Equities universe ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS equities (
    id               SERIAL PRIMARY KEY,
    symbol           TEXT UNIQUE NOT NULL,
    name             TEXT NOT NULL,
    exchange         TEXT,
    asset_class      TEXT NOT NULL DEFAULT 'us_equity',
    gics_sector      TEXT,
    gics_industry    TEXT,
    gics_sub_industry TEXT,
    country          TEXT NOT NULL DEFAULT 'US',
    currency         TEXT NOT NULL DEFAULT 'USD',
    is_tracked       BOOLEAN NOT NULL DEFAULT FALSE,
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    market_cap_tier  TEXT,
    added_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delisted_at      TIMESTAMPTZ
);

-- ── Company people ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS company_people (
    id             SERIAL PRIMARY KEY,
    equity_id      INTEGER REFERENCES equities(id),
    name           TEXT NOT NULL,
    title          TEXT,
    level          TEXT,
    twitter_handle TEXT,
    linkedin_url   TEXT,
    start_date     DATE,
    end_date       DATE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Fundamentals ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fundamentals (
    id                  SERIAL PRIMARY KEY,
    equity_id           INTEGER REFERENCES equities(id) NOT NULL,
    period_type         TEXT NOT NULL,
    period_end          DATE NOT NULL,
    fiscal_year         INTEGER,
    fiscal_quarter      INTEGER,
    source              TEXT NOT NULL DEFAULT 'yfinance',
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Income Statement (stored as integer cents to avoid float precision loss)
    revenue             BIGINT,
    gross_profit        BIGINT,
    operating_income    BIGINT,
    net_income          BIGINT,
    ebitda              BIGINT,
    eps_basic           NUMERIC(12,4),
    eps_diluted         NUMERIC(12,4),
    shares_basic        BIGINT,
    shares_diluted      BIGINT,

    -- Balance Sheet
    cash_and_equiv      BIGINT,
    total_assets        BIGINT,
    total_liabilities   BIGINT,
    total_equity        BIGINT,
    total_debt          BIGINT,
    net_debt            BIGINT,

    -- Cash Flow
    operating_cash_flow BIGINT,
    capex               BIGINT,
    free_cash_flow      BIGINT,
    dividends_paid      BIGINT,

    -- Computed ratios (stored to avoid recomputation on every read)
    gross_margin        NUMERIC(8,4),
    operating_margin    NUMERIC(8,4),
    net_margin          NUMERIC(8,4),
    roe                 NUMERIC(8,4),
    roa                 NUMERIC(8,4),
    roic                NUMERIC(8,4),
    debt_to_equity      NUMERIC(8,4),
    current_ratio       NUMERIC(8,4),
    quick_ratio         NUMERIC(8,4),
    revenue_growth_yoy  NUMERIC(8,4),
    eps_growth_yoy      NUMERIC(8,4),

    -- Valuation snapshot at time of fetch
    price_at_fetch      NUMERIC(12,4),
    market_cap          BIGINT,
    pe_ratio            NUMERIC(8,4),
    pb_ratio            NUMERIC(8,4),
    ps_ratio            NUMERIC(8,4),
    ev_ebitda           NUMERIC(8,4),
    ev_revenue          NUMERIC(8,4),

    UNIQUE(equity_id, period_type, period_end)
);

-- ── Analyst estimates ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS analyst_estimates (
    id                   SERIAL PRIMARY KEY,
    equity_id            INTEGER REFERENCES equities(id) NOT NULL,
    fetched_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    target_price_low     NUMERIC(12,4),
    target_price_mean    NUMERIC(12,4),
    target_price_high    NUMERIC(12,4),
    recommendation       TEXT,
    num_analysts         INTEGER,
    earnings_est_next_q  NUMERIC(12,4),
    revenue_est_next_q   BIGINT
);

-- ── Market bars (TimescaleDB hypertable) ────────────────────────────────────
CREATE TABLE IF NOT EXISTS market_bars (
    time        TIMESTAMPTZ NOT NULL,
    equity_id   INTEGER NOT NULL,
    timeframe   TEXT NOT NULL,
    open        NUMERIC(12,4),
    high        NUMERIC(12,4),
    low         NUMERIC(12,4),
    close       NUMERIC(12,4),
    volume      BIGINT,
    vwap        NUMERIC(12,4),
    trade_count INTEGER
);

-- ── Market quotes (latest snapshot per ticker) ──────────────────────────────
CREATE TABLE IF NOT EXISTS market_quotes (
    equity_id   INTEGER PRIMARY KEY REFERENCES equities(id),
    bid_price   NUMERIC(12,4),
    ask_price   NUMERIC(12,4),
    bid_size    INTEGER,
    ask_size    INTEGER,
    last_price  NUMERIC(12,4),
    updated_at  TIMESTAMPTZ
);

-- ── Macro series ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS macro_series (
    id       SERIAL PRIMARY KEY,
    code     TEXT UNIQUE NOT NULL,
    name     TEXT NOT NULL,
    category TEXT,
    source   TEXT
);

CREATE TABLE IF NOT EXISTS macro_data (
    time      TIMESTAMPTZ NOT NULL,
    series_id INTEGER REFERENCES macro_series(id),
    value     NUMERIC(16,6),
    PRIMARY KEY (time, series_id)
);

-- ── News items ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS news_items (
    id              SERIAL PRIMARY KEY,
    external_id     TEXT UNIQUE,
    equity_ids      INTEGER[],
    headline        TEXT NOT NULL,
    summary         TEXT,
    body_text       TEXT,
    source          TEXT,
    url             TEXT,
    published_at    TIMESTAMPTZ NOT NULL,
    sentiment_score NUMERIC(4,3),
    category        TEXT,
    embedding       vector(1536),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── SEC filings ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sec_filings (
    id           SERIAL PRIMARY KEY,
    equity_id    INTEGER REFERENCES equities(id),
    filing_type  TEXT NOT NULL,
    period_end   DATE,
    filed_at     TIMESTAMPTZ,
    url          TEXT,
    full_text    TEXT,
    embedding    vector(1536),
    processed    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Agent models (versioned intelligence layer) ─────────────────────────────
CREATE TABLE IF NOT EXISTS agent_models (
    id              SERIAL PRIMARY KEY,
    agent_type      TEXT NOT NULL,
    entity_key      TEXT NOT NULL,
    version         INTEGER NOT NULL,
    model_schema    JSONB NOT NULL,
    analysis        JSONB NOT NULL,
    supporting_data JSONB NOT NULL,
    predictions     JSONB NOT NULL,
    explanation     TEXT NOT NULL,
    data_as_of      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(agent_type, entity_key, version)
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id           SERIAL PRIMARY KEY,
    agent_type   TEXT NOT NULL,
    entity_key   TEXT NOT NULL,
    model_id     INTEGER REFERENCES agent_models(id),
    status       TEXT NOT NULL,
    error        TEXT,
    duration_ms  INTEGER,
    triggered_by TEXT,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at  TIMESTAMPTZ
);

-- ── Trading Job Registry ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS trading_jobs (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    strategy    TEXT NOT NULL,
    job_type    TEXT NOT NULL DEFAULT 'user',
    owner_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,
    config      JSONB NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'idle',
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (owner_id, name)
);

CREATE TABLE IF NOT EXISTS trading_sessions (
    id                  SERIAL PRIMARY KEY,
    job_id              INTEGER NOT NULL REFERENCES trading_jobs(id) ON DELETE CASCADE,
    session_date        DATE NOT NULL,
    orb_high            NUMERIC(12,4),
    orb_low             NUMERIC(12,4),
    orb_width           NUMERIC(8,4),
    orb_established_at  TIMESTAMPTZ,
    status              TEXT NOT NULL DEFAULT 'open',
    total_entries       INTEGER NOT NULL DEFAULT 0,
    total_exits         INTEGER NOT NULL DEFAULT 0,
    daily_pnl_cents     BIGINT NOT NULL DEFAULT 0,
    opened_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at           TIMESTAMPTZ,
    UNIQUE (job_id, session_date)
);

CREATE TABLE IF NOT EXISTS trading_events (
    id              BIGSERIAL,
    time            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    job_id          INTEGER NOT NULL REFERENCES trading_jobs(id) ON DELETE CASCADE,
    session_id      INTEGER REFERENCES trading_sessions(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL,
    direction       TEXT,
    contract_symbol TEXT,
    contracts       INTEGER,
    spy_price       NUMERIC(12,4),
    orb_high        NUMERIC(12,4),
    orb_low         NUMERIC(12,4),
    signal_streak   INTEGER,
    entry_counts    JSONB,
    option_price    NUMERIC(12,4),
    pnl_cents       BIGINT,
    order_id        TEXT,
    reason          TEXT,
    decision        TEXT,
    meta            JSONB
);

-- ── Indexes ─────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_fundamentals_equity_period
    ON fundamentals(equity_id, period_end DESC);
CREATE INDEX IF NOT EXISTS idx_news_items_published
    ON news_items(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_models_entity
    ON agent_models(agent_type, entity_key, version DESC);
CREATE INDEX IF NOT EXISTS idx_sec_filings_equity
    ON sec_filings(equity_id, filed_at DESC);
CREATE INDEX IF NOT EXISTS idx_trading_events_job_id
    ON trading_events(job_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_trading_events_type
    ON trading_events(event_type, time DESC);
"""

HYPERTABLES_MIGRATIONS = """
SELECT create_hypertable('market_bars', 'time', if_not_exists => TRUE);
SELECT create_hypertable('macro_data', 'time', if_not_exists => TRUE);
SELECT create_hypertable('trading_events', 'time', if_not_exists => TRUE);
"""

SEED_DATA = """
-- GICS Sectors
INSERT INTO gics_sectors(code, name) VALUES
    ('10', 'Energy'),
    ('15', 'Materials'),
    ('20', 'Industrials'),
    ('25', 'Consumer Discretionary'),
    ('30', 'Consumer Staples'),
    ('35', 'Health Care'),
    ('40', 'Financials'),
    ('45', 'Information Technology'),
    ('50', 'Communication Services'),
    ('55', 'Utilities'),
    ('60', 'Real Estate')
ON CONFLICT (code) DO NOTHING;

-- Tracked equities: HOOD, NVDA, KO
INSERT INTO equities(symbol, name, exchange, gics_sector, gics_industry, gics_sub_industry, is_tracked, market_cap_tier) VALUES
    ('HOOD', 'Robinhood Markets Inc', 'NASDAQ', 'Financials', 'Capital Markets', 'Financial Exchanges & Data', TRUE, 'mid'),
    ('NVDA', 'NVIDIA Corporation', 'NASDAQ', 'Information Technology', 'Semiconductors & Semiconductor Equipment', 'Semiconductors', TRUE, 'mega'),
    ('KO',   'The Coca-Cola Company', 'NYSE', 'Consumer Staples', 'Beverages', 'Soft Drinks & Non-alcoholic Beverages', TRUE, 'mega')
ON CONFLICT (symbol) DO UPDATE
    SET name = EXCLUDED.name,
        gics_sector = EXCLUDED.gics_sector,
        gics_industry = EXCLUDED.gics_industry,
        is_tracked = EXCLUDED.is_tracked,
        market_cap_tier = EXCLUDED.market_cap_tier;

-- System default job: SPY ORB 0DTE (safe against NULL owner_id unique conflict)
INSERT INTO trading_jobs (name, strategy, job_type, owner_id, config)
SELECT 'spy_orb_0dte', 'orb', 'system', NULL,
       '{"symbol":"SPY","risk_pct":0.03,"max_entries":3,"tp_mult":1.80,"sl_mult":0.45}'
WHERE NOT EXISTS (
    SELECT 1 FROM trading_jobs WHERE name = 'spy_orb_0dte' AND owner_id IS NULL
);
"""


async def _seed_admin(pool: asyncpg.Pool) -> None:
    email = os.getenv("ADMIN_EMAIL")
    password = os.getenv("ADMIN_PASSWORD")
    if not email or not password:
        return
    from app.auth.db import create_user, get_user_by_email
    from app.auth.security import hash_password

    async with pool.acquire() as conn:
        existing = await get_user_by_email(conn, email)
        if existing:
            return
        await create_user(conn, email, hash_password(password), role="admin")
        print(f"[startup] Admin user seeded: {email}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if not os.getenv("JWT_SECRET_KEY"):
        raise RuntimeError(
            "JWT_SECRET_KEY environment variable is not set. "
            "Set it to a random 64-character hex string before starting the server."
        )

    db_url = os.getenv("DATABASE_URL")
    app.state.db_url = db_url

    async def _init_connection(conn: asyncpg.Connection) -> None:
        await conn.set_type_codec(
            "jsonb",
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )
        await conn.set_type_codec(
            "json",
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )

    pool = await asyncpg.create_pool(db_url, init=_init_connection)
    app.state.pool = pool

    try:
        async with pool.acquire() as conn:
            await conn.execute(DB_MIGRATIONS)
        async with pool.acquire() as conn:
            await conn.execute(HYPERTABLES_MIGRATIONS)
        async with pool.acquire() as conn:
            await conn.execute(SEED_DATA)
        # Reset any user jobs left in 'running' state from a previous process.
        # User jobs have no persistent backing loop — they are orphaned after restart.
        # System jobs are restarted explicitly via POST /trading/start on the next request.
        async with pool.acquire() as conn:
            reset_count = await conn.fetchval(
                """
                WITH reset AS (
                    UPDATE trading_jobs
                    SET status = 'idle', updated_at = NOW()
                    WHERE status = 'running' AND job_type = 'user'
                    RETURNING id
                )
                SELECT COUNT(*) FROM reset
                """
            )
            if reset_count:
                print(f"[startup] Reset {reset_count} stale user job(s) to idle.")
            # Also close any open sessions for user jobs that were reset
            await conn.execute(
                """
                UPDATE trading_sessions
                SET status = 'closed', closed_at = NOW()
                WHERE status = 'open'
                  AND job_id IN (
                      SELECT id FROM trading_jobs
                      WHERE job_type = 'user' AND status = 'idle'
                  )
                  AND closed_at IS NULL
                """
            )
        print("[startup] Migrations, hypertables, and seed data applied.")
    except Exception as e:
        print(f"[startup] DB migration warning: {e}")

    await _seed_admin(pool)

    yield

    await pool.close()


app = FastAPI(title="Loaded API", version="0.1.0", lifespan=lifespan)

# ── Middleware ─────────────────────────────────────────────────────────────────

app.add_middleware(DocsAuthMiddleware)

_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
_allow_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()] or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=True,
)

# ── Rate limiter ───────────────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

# ── Routers ────────────────────────────────────────────────────────────────────

app.include_router(auth_router)

_auth_dep = [Depends(get_current_user)]
app.include_router(strategies_router, dependencies=_auth_dep)
app.include_router(alpaca_router, dependencies=_auth_dep)
app.include_router(marketdata_router, dependencies=_auth_dep)
app.include_router(agents_router, prefix="/agents", dependencies=_auth_dep)
app.include_router(trading_router, prefix="/trading", dependencies=_auth_dep)


# ── DB helpers ─────────────────────────────────────────────────────────────────


async def get_db() -> AsyncGenerator[asyncpg.Connection, None]:
    """Yield a single connection from the pool."""
    async with app.state.pool.acquire() as conn:
        yield conn


async def db_ok() -> bool:
    try:
        async with app.state.pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception:
        return False


# ── Health ─────────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict[str, Any]:
    db = await db_ok()
    alpaca_connected, alpaca_error = alpaca_ok()
    return {
        "status": "online",
        "db": "connected" if db else "disconnected",
        "alpaca": "connected" if alpaca_connected else "disconnected",
        "alpaca_error": alpaca_error,
        "timestamp": datetime.now(UTC).isoformat(),
    }
