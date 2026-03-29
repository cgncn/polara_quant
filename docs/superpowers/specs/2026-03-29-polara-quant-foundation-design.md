# Polara Quant — Foundation Design Spec

**Date:** 2026-03-29
**Phase:** 0-1 (Foundation)
**Status:** Active

---

## What Is Polara Quant?

Polara Quant is an automated research and paper-trading platform. It:

1. Pulls market data from Interactive Brokers (IB Gateway) and/or data vendors
2. Generates trading signals via strategy sleeves (isolated Python modules)
3. Applies risk controls before any order is submitted
4. Places paper orders through a single broker adapter
5. Validates all results rigorously before any live capital is ever deployed

The platform is designed for iterative, validated deployment: paper trading first, manual promotion gates at every phase boundary, no strategy self-promotion.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Package manager | uv |
| API framework | FastAPI + Uvicorn (port 8000) |
| Data validation | Pydantic v2 (strict mode) |
| ORM | SQLAlchemy 2.0 async |
| Database (paper) | SQLite via aiosqlite |
| Database (pre-live) | PostgreSQL |
| Migrations | Alembic |
| Containerisation | Docker Compose |
| Market data storage | Parquet + DuckDB |
| Broker | IB Gateway (paper account first) |
| Linting | Ruff |
| Type checking | mypy (strict) |
| Testing | pytest + pytest-asyncio + httpx |

---

## Non-Negotiable Operating Rules

These rules are enforced by code review, mypy, and CI. No exceptions.

### 1. Decimal-Only for Money
`float` is **never** used for prices, quantities, commissions, P&L, or any financial value. All such fields use `decimal.Decimal`. This prevents float rounding errors from silently corrupting trade results.

### 2. UTC-Aware Datetimes
Every `datetime` object must carry UTC timezone info. Use `datetime.now(UTC)` or `datetime(..., tzinfo=UTC)`. The deprecated `datetime.utcnow()` returns a naive datetime and is banned. Naive datetimes anywhere in the codebase are a bug.

### 3. Pydantic Strict Mode
All Pydantic models are defined with `model_config = ConfigDict(strict=True)`. This prevents silent coercions (e.g., `"123"` silently becoming `123`). Incorrect types raise a `ValidationError` immediately.

### 4. Postgres-Compatible SQL Only
The database starts as SQLite for local development but must migrate to PostgreSQL pre-live. All SQL written (including SQLAlchemy column types and Alembic migrations) must be compatible with PostgreSQL. No SQLite-specific types (`BLOB`, `TEXT` for booleans, etc.).

### 5. Single Broker Adapter
Only one service (`polara.broker`) is permitted to communicate with IB Gateway. No other module imports or instantiates broker connection objects. This enforces a single point of control and simplifies audit trails.

### 6. Manual Promotion Gates
No strategy may promote itself from paper to live. All phase transitions (paper → pre-live → live) require explicit human approval and a documented review step.

---

## Repository Structure

```
polara_quant/
├── src/
│   └── polara/
│       ├── __init__.py          # package version
│       ├── constants.py         # shared constants (UTC, Decimal contexts, etc.)
│       ├── schemas/             # Pydantic models
│       │   ├── market.py        # OHLCV, ticker, instrument schemas
│       │   ├── orders.py        # order request/response schemas
│       │   ├── signals.py       # strategy signal schemas
│       │   └── events.py        # internal event bus schemas
│       ├── db/
│       │   ├── __init__.py
│       │   └── connection.py    # async SQLAlchemy engine + session factory
│       └── api/
│           ├── __init__.py
│           ├── main.py          # FastAPI app factory
│           └── routes/
│               ├── __init__.py
│               └── health.py    # GET /health endpoint
├── tests/
│   ├── __init__.py
│   ├── test_schemas.py          # Pydantic model tests
│   └── test_health.py           # API health endpoint tests
├── docs/
│   └── superpowers/
│       └── specs/               # design specs (this file)
├── alembic/                     # DB migrations (Phase 0-1+)
├── scripts/                     # operational scripts
├── pyproject.toml
├── CLAUDE.md                    # AI coding rules
├── README.md
└── .gitignore
```

**Phase 2+ directories (do not create yet):**
- `src/polara/broker/` — IB Gateway adapter
- `src/polara/order_manager/` — order lifecycle management
- `src/polara/risk_guard/` — pre-trade risk checks
- `src/polara/research_engine/` — signal generation
- `src/polara/validator/` — post-trade validation

---

## Phase 0-1 Scope (Foundation Only)

Phase 0-1 delivers the structural skeleton. Nothing else.

**In scope:**
- Project configuration (`pyproject.toml`, `CLAUDE.md`, `.gitignore`)
- Source package skeleton (`src/polara/` with empty placeholder modules)
- Shared constants module (UTC timezone, Decimal quantize context)
- Core Pydantic schemas (market data, orders, signals, events)
- Async SQLAlchemy engine and session factory (SQLite)
- FastAPI app with `/health` endpoint
- Tests for schemas and health endpoint
- Docker Compose file (app + optional DB service)

**Explicitly out of scope for Phase 0-1:**
- Broker adapter (IB Gateway connection)
- Order manager
- Risk guard
- Research engine / strategy sleeves
- Validator / post-trade analysis
- Data ingestion pipeline
- Any live or paper trading execution

---

## Design Decisions and Rationale

### Why SQLite first?
SQLite requires zero infrastructure for local development and CI. The constraint to use only Postgres-compatible SQL means the migration to PostgreSQL is a configuration change, not a rewrite.

### Why uv?
uv provides deterministic, fast dependency resolution with lockfile support. It is a drop-in replacement for pip/venv workflows and is significantly faster in CI.

### Why Pydantic strict mode?
Financial data tolerates no silent coercions. A string `"100.5"` must not silently become the float `100.5` in a price field. Strict mode forces callers to pass the correct type, surfacing integration bugs at the boundary rather than deep in calculation logic.

### Why a single broker adapter service?
Centralising all IB Gateway communication simplifies:
- Rate limiting and connection pooling
- Audit logging of all broker interactions
- Testing (mock the adapter, not scattered IB calls)
- Future broker switching (swap one adapter, nothing else changes)

### Why manual promotion gates?
Automated trading platforms that self-promote strategies have a well-documented history of catastrophic losses. Manual gates ensure a human reviews all metrics, drawdown, and edge cases before real capital is at risk.
