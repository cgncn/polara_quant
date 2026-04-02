# Phase 2 — Broker Adapter Design

**Date:** 2026-04-02
**Status:** Approved
**Phase:** 2 (builds on Phase 0-1 foundation)

---

## Context

Phase 0-1 delivered: FastAPI health endpoint, async SQLAlchemy + SQLite, Pydantic v2 schemas (Bar, Quote, OrderRequest, Fill, Signal, TargetPosition, Event), Alembic migrations, Docker Compose deployment on Hetzner CPX22 VM (Ubuntu 24.04, IP: 178.104.32.74).

Phase 2 adds the broker adapter — the single service that owns all communication with Interactive Brokers Gateway. Nothing else in the system talks to IB directly.

---

## Non-Negotiable Rules (from CLAUDE.md)

1. No `float` for money, prices, commissions, quantities — always `Decimal`
2. All datetimes UTC-aware — `datetime.now(UTC)`, never `datetime.utcnow()`
3. Pydantic models `strict=True` — no silent coercion
4. PostgreSQL-compatible SQL only — no SQLite-specific syntax
5. **One service owns the broker adapter** — only `src/polara/broker/` talks to IB Gateway
6. No strategy self-promotion — promotion gates are always manual

---

## Decisions Made

| Decision | Choice | Rationale |
|---|---|---|
| IB Gateway location | Hetzner VM (headless) | Always-on, no Mac dependency |
| IB Gateway runner | `ghcr.io/gnzsnz/ib-gateway` Docker image (bundles IBC) | Standard headless approach |
| Python IB library | `ib_async` | Modern asyncio fork of ib_insync, fits FastAPI stack |
| Adapter location | Module inside `polara-api` (Option B) | Simpler for single-developer, single-VM; extractable later |
| Trading mode | Paper Trading first | Port 4003 (IB standard paper port) |
| Credentials storage | `.env` file on VM only — never committed to git | `.gitignore` already excludes `.env` |
| Market data streaming | Phase 3 — not in Phase 2 | Keep scope lean |

---

## Architecture

### New Directory Structure

```
src/polara/
├── broker/                        ← NEW module
│   ├── __init__.py
│   ├── client.py                  # ib_async connection manager
│   ├── adapter.py                 # business logic
│   └── schemas.py                 # IB-specific Pydantic models
└── api/routes/
    └── broker.py                  ← NEW route file

migrations/versions/
└── 0002_broker.py                 ← NEW migration

docker-compose.yml                 ← UPDATED (add ib-gateway service)
.env                               ← VM only, never in git
```

### Services in Docker Compose

```
┌─────────────────────────────────────────────────┐
│  Hetzner VM (178.104.32.74)                     │
│                                                  │
│  ┌─────────────────┐    ┌──────────────────────┐ │
│  │  polara-api     │    │  ib-gateway          │ │
│  │  port 8000      │◄──►│  port 4003 (paper)   │ │
│  │  FastAPI +      │    │  IBC auto-login       │ │
│  │  broker module  │    │  gnzsnz/ib-gateway    │ │
│  └────────┬────────┘    └──────────────────────┘ │
│           │                                       │
│  ┌────────▼────────┐                             │
│  │  SQLite DB      │                             │
│  │  ./data/        │                             │
│  └─────────────────┘                             │
└─────────────────────────────────────────────────┘
```

---

## Module Design

### `src/polara/broker/client.py`

Owns the `ib_async` connection. Responsibilities:
- Connect to IB Gateway on startup (host: `ib-gateway`, port: `4003`)
- Disconnect cleanly on shutdown
- Auto-reconnect with exponential backoff on drop
- Expose connection status (`connected: bool`)
- Single instance managed via FastAPI lifespan (stored on `app.state.ib_client`)

Nothing outside `broker/` imports from this file directly — all access goes through `adapter.py`.

### `src/polara/broker/adapter.py`

Business logic layer. Responsibilities:
- `place_order(order_request: OrderRequest) -> str` — submits to IB, returns IB order ID
- `cancel_order(order_id: UUID) -> None`
- `get_account() -> AccountInfo`
- `get_positions() -> list[Position]`
- `get_pnl_snapshot() -> PnLSnapshot`
- Saves fills to DB when IB callbacks fire
- Updates order status in DB on state changes
- Background task: snapshots P&L to DB every 60 seconds

### `src/polara/broker/schemas.py`

IB-specific Pydantic models, all with `ConfigDict(strict=True)`:

- **`AccountInfo`**: net_liquidation (Decimal), cash (Decimal), unrealised_pnl (Decimal), realised_pnl (Decimal), currency (str), timestamp (UTC datetime)
- **`Position`**: symbol (str), quantity (Decimal), avg_cost (Decimal), unrealised_pnl (Decimal), updated_at (UTC datetime)
- **`PnLSnapshot`**: net_liquidation (Decimal), cash (Decimal), unrealised_pnl (Decimal), realised_pnl (Decimal), snapshot_at (UTC datetime)
- **`BrokerStatus`**: connected (bool), ib_server_time (UTC datetime | None), account_id (str | None)
- **`OrderStatus`**: order_id (UUID), ib_order_id (int | None), status (str), submitted_at (UTC datetime), filled_at (UTC datetime | None)

---

## Database Schema (migration `0002_broker`)

All money/price columns stored as `TEXT` (Decimal serialised as string). All datetime columns stored as `TEXT` (UTC ISO 8601). No floats anywhere.

```sql
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL UNIQUE,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity TEXT NOT NULL,
    limit_price TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'submitted', 'filled', 'cancelled', 'error')),
    ib_order_id INTEGER,
    strategy_id TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    filled_at TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fills (
    id TEXT PRIMARY KEY,
    fill_id TEXT NOT NULL UNIQUE,
    order_id TEXT NOT NULL REFERENCES orders(order_id),
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    filled_quantity TEXT NOT NULL,
    fill_price TEXT NOT NULL,
    commission TEXT NOT NULL,
    filled_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS positions (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL UNIQUE,
    quantity TEXT NOT NULL,
    avg_cost TEXT NOT NULL,
    unrealised_pnl TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS account_snapshots (
    id TEXT PRIMARY KEY,
    net_liquidation TEXT NOT NULL,
    cash TEXT NOT NULL,
    unrealised_pnl TEXT NOT NULL,
    realised_pnl TEXT NOT NULL,
    snapshot_at TEXT NOT NULL
);
```

---

## API Endpoints (`src/polara/api/routes/broker.py`)

All money values in requests and responses use `Decimal` (serialised as strings in JSON).

| Method | Path | Description | Success | Error |
|---|---|---|---|---|
| `GET` | `/broker/status` | IB Gateway connection status | 200 BrokerStatus | — |
| `GET` | `/broker/account` | Live account balance + P&L | 200 AccountInfo | 503 if disconnected |
| `GET` | `/broker/positions` | Current open positions | 200 list[Position] | 503 if disconnected |
| `POST` | `/broker/orders` | Place a paper order | 201 OrderStatus | 400 validation, 503 disconnected |
| `GET` | `/broker/orders` | List all orders | 200 list[OrderStatus] | — |
| `GET` | `/broker/orders/{order_id}` | Single order + its fills | 200 OrderWithFills | 404 not found |
| `DELETE` | `/broker/orders/{order_id}` | Cancel an order | 200 OrderStatus | 404, 503 |
| `GET` | `/broker/pnl/history` | Historical P&L snapshots | 200 list[PnLSnapshot] | — |

---

## Docker Compose Changes

Add `ib-gateway` service to `docker-compose.yml`:

```yaml
  ib-gateway:
    image: ghcr.io/gnzsnz/ib-gateway:latest
    restart: unless-stopped
    environment:
      - TWS_USERID=${IB_USERNAME}
      - TWS_PASSWORD=${IB_PASSWORD}
      - TRADING_MODE=paper
      - TWS_SETTINGS_PATH=/home/ibgateway/Jts
      - TWOFA_TIMEOUT_ACTION=restart
    ports:
      - "4003:4003"    # paper trading API port
    volumes:
      - ./data/jts:/home/ibgateway/Jts
```

The `polara-api` service gains:
```yaml
    depends_on:
      - ib-gateway
    environment:
      - IB_HOST=ib-gateway
      - IB_PORT=4003
      - IB_CLIENT_ID=1
```

---

## `.env` File (VM only — never committed)

```
IB_USERNAME=your_ib_username
IB_PASSWORD=your_ib_password
DATABASE_URL=sqlite+aiosqlite:///./data/polara.db
```

This file lives at `~/polara_quant/.env` on the Hetzner VM. It is listed in `.gitignore` and must never be pushed to GitHub.

---

## Lifecycle Management

IB Gateway connection managed in `api/main.py` lifespan:

```python
@asynccontextmanager
async def _lifespan(app: FastAPI):
    # startup
    ib_client = IBClient(host=IB_HOST, port=IB_PORT, client_id=IB_CLIENT_ID)
    await ib_client.connect()
    app.state.ib_client = ib_client
    # start P&L snapshot background task (every 60s)
    app.state.pnl_task = asyncio.create_task(pnl_snapshot_loop(ib_client))
    yield
    # shutdown
    app.state.pnl_task.cancel()
    await ib_client.disconnect()
```

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| IB Gateway unreachable at startup | Log warning, continue — endpoints return 503 until connected |
| Connection drops mid-session | Auto-reconnect with backoff (1s, 2s, 4s, 8s, max 60s) |
| Order rejected by IB | Status → "error", error_message stored in DB |
| Order cancel on already-filled order | Return 400 with clear message |
| IB Gateway 2FA timeout | Container restarts (TWOFA_TIMEOUT_ACTION=restart) |

---

## Testing Strategy

- **Unit tests** (`tests/test_broker_schemas.py`): Validate all new Pydantic models — Decimal enforcement, UTC datetimes, status CHECK values
- **Adapter tests** (`tests/test_broker_adapter.py`): Mock `ib_async` client, test order flow (submit → fill → DB state)
- **Route tests** (`tests/test_broker_routes.py`): httpx AsyncClient, mock adapter, test all 8 endpoints including 503 when disconnected
- **Migration test** (`tests/test_migrations.py`): Extended to verify 4 new tables created/dropped correctly

---

## New Dependencies to Add to `pyproject.toml`

```toml
"ib_async>=0.9",
```

> **Note:** Verify exact PyPI package name at implementation time. The package may be published as `ib_async`, `ib-insync`, or a named fork. Confirm with `pip search` or PyPI before pinning.

---

## What is NOT in Phase 2

- Live market data streaming (bars/quotes from IB) → Phase 3
- Strategy sleeves / signal generation → Phase 3+
- Order manager / risk guard → Phase 3+
- Research engine → Phase 4+
- Live trading (non-paper) → Phase 5+ (requires manual promotion gate)
- Control plane UI → Phase 6

---

## Phase 2 Exit Criteria

- [ ] IB Gateway running headless on VM, auto-reconnects after restart
- [ ] `GET /broker/status` returns `{"connected": true}`
- [ ] Paper order submitted via `POST /broker/orders`, fill received and stored in DB
- [ ] `GET /broker/account` returns real account values with Decimal precision
- [ ] `GET /broker/positions` reflects actual paper positions
- [ ] `DELETE /broker/orders/{id}` cancels an open order
- [ ] `GET /broker/pnl/history` returns snapshots (at least one after 60s)
- [ ] All tests pass (`uv run pytest`)
- [ ] No floats anywhere in broker module (`uv run ruff check src/`)
