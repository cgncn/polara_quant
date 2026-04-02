# Phase 2 — Broker Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fully-working Interactive Brokers paper-trading adapter inside `polara-api`, surfaced via 8 REST endpoints.

**Architecture:** A new `src/polara/broker/` module contains all IB communication. `client.py` owns the connection lifecycle; `adapter.py` owns business logic; `schemas.py` owns IB-specific Pydantic models. Nothing outside `broker/` touches `ib_async` directly. The FastAPI lifespan manages startup/shutdown and a 60-second P&L snapshot background task.

**Tech Stack:** Python 3.12, ib_async ≥ 0.9, FastAPI, SQLAlchemy 2 async + aiosqlite, Pydantic v2 strict, Alembic, Docker Compose + ghcr.io/gnzsnz/ib-gateway.

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `pyproject.toml` | Modify | Add `ib_async>=0.9` dependency |
| `src/polara/broker/__init__.py` | Create | Package marker |
| `src/polara/broker/schemas.py` | Create | AccountInfo, Position, PnLSnapshot, BrokerStatus, OrderStatus, OrderWithFills — all strict=True |
| `src/polara/broker/client.py` | Create | ib_async connection manager — connect/disconnect/auto-reconnect/`connected` property |
| `src/polara/broker/adapter.py` | Create | Business logic — place_order, cancel_order, get_account, get_positions, get_pnl_snapshot, fill callbacks, pnl_snapshot_loop |
| `src/polara/api/routes/broker.py` | Create | 8 REST endpoints |
| `src/polara/api/main.py` | Modify | Update lifespan to start IBClient + pnl_task; include broker router |
| `migrations/versions/0002_broker.py` | Create | Create orders, fills, positions, account_snapshots tables |
| `docker-compose.yml` | Modify | Add ib-gateway service; add IB env vars + depends_on to polara-api |
| `tests/test_broker_schemas.py` | Create | Pydantic model validation tests |
| `tests/test_broker_adapter.py` | Create | Adapter unit tests with mocked ib_async client |
| `tests/test_broker_routes.py` | Create | Route integration tests with mocked adapter |
| `tests/test_migrations.py` | Modify | Extend to assert 4 new tables exist after 0002 upgrade |

---

## Task 1: Add `ib_async` dependency and broker package skeleton

**Files:**
- Modify: `pyproject.toml`
- Create: `src/polara/broker/__init__.py`

- [ ] **Step 1: Add ib_async to pyproject.toml**

Edit `pyproject.toml` dependencies list:

```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic>=2.7",
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "aiosqlite>=0.20",
    "greenlet>=3.3.2",
    "ib_async>=0.9",
]
```

- [ ] **Step 2: Verify the package name on PyPI and sync**

```bash
uv add ib_async
```

Expected: `ib_async` added to `uv.lock`. If PyPI returns "not found", try `ib-async` or check https://pypi.org/search/?q=ib_async and update to the correct name.

- [ ] **Step 3: Create the broker package marker**

Create `src/polara/broker/__init__.py`:

```python
```

(Empty file — package marker only.)

- [ ] **Step 4: Confirm import works**

```bash
uv run python -c "import ib_async; print(ib_async.__version__)"
```

Expected: version string printed, no ImportError.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/polara/broker/__init__.py
git commit -m "feat: add ib_async dependency and broker package skeleton"
```

---

## Task 2: Broker schemas

**Files:**
- Create: `src/polara/broker/schemas.py`
- Create: `tests/test_broker_schemas.py`

- [ ] **Step 1: Write the failing tests first**

Create `tests/test_broker_schemas.py`:

```python
"""Tests for broker-specific Pydantic schemas."""
from decimal import Decimal
from datetime import datetime, UTC
from uuid import uuid4
import pytest
from pydantic import ValidationError

from polara.broker.schemas import (
    AccountInfo,
    Position,
    PnLSnapshot,
    BrokerStatus,
    OrderStatus,
    OrderWithFills,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


# ── AccountInfo ────────────────────────────────────────────────────────────────

def test_account_info_valid():
    a = AccountInfo(
        net_liquidation=Decimal("100000.00"),
        cash=Decimal("50000.00"),
        unrealised_pnl=Decimal("500.00"),
        realised_pnl=Decimal("200.00"),
        currency="USD",
        timestamp=utcnow(),
    )
    assert a.net_liquidation == Decimal("100000.00")


def test_account_info_rejects_float():
    with pytest.raises(ValidationError):
        AccountInfo(
            net_liquidation=100000.0,  # float — must be rejected
            cash=Decimal("50000.00"),
            unrealised_pnl=Decimal("0"),
            realised_pnl=Decimal("0"),
            currency="USD",
            timestamp=utcnow(),
        )


def test_account_info_rejects_naive_datetime():
    from datetime import datetime
    with pytest.raises(ValidationError):
        AccountInfo(
            net_liquidation=Decimal("100000"),
            cash=Decimal("50000"),
            unrealised_pnl=Decimal("0"),
            realised_pnl=Decimal("0"),
            currency="USD",
            timestamp=datetime(2026, 1, 1),  # naive — must be rejected
        )


# ── Position ───────────────────────────────────────────────────────────────────

def test_position_valid():
    p = Position(
        symbol="AAPL",
        quantity=Decimal("10"),
        avg_cost=Decimal("150.00"),
        unrealised_pnl=Decimal("50.00"),
        updated_at=utcnow(),
    )
    assert p.symbol == "AAPL"


def test_position_rejects_float_quantity():
    with pytest.raises(ValidationError):
        Position(
            symbol="AAPL",
            quantity=10.0,  # float — must be rejected
            avg_cost=Decimal("150.00"),
            unrealised_pnl=Decimal("0"),
            updated_at=utcnow(),
        )


# ── PnLSnapshot ────────────────────────────────────────────────────────────────

def test_pnl_snapshot_valid():
    s = PnLSnapshot(
        net_liquidation=Decimal("100000"),
        cash=Decimal("50000"),
        unrealised_pnl=Decimal("500"),
        realised_pnl=Decimal("200"),
        snapshot_at=utcnow(),
    )
    assert s.snapshot_at.tzinfo is not None


# ── BrokerStatus ───────────────────────────────────────────────────────────────

def test_broker_status_connected():
    s = BrokerStatus(connected=True, ib_server_time=utcnow(), account_id="DU123456")
    assert s.connected is True


def test_broker_status_disconnected():
    s = BrokerStatus(connected=False, ib_server_time=None, account_id=None)
    assert s.ib_server_time is None


# ── OrderStatus ────────────────────────────────────────────────────────────────

def test_order_status_valid():
    s = OrderStatus(
        order_id=uuid4(),
        ib_order_id=42,
        status="submitted",
        submitted_at=utcnow(),
        filled_at=None,
    )
    assert s.status == "submitted"


def test_order_status_rejects_invalid_status():
    with pytest.raises(ValidationError):
        OrderStatus(
            order_id=uuid4(),
            ib_order_id=None,
            status="flying",  # not a valid status
            submitted_at=utcnow(),
            filled_at=None,
        )


# ── OrderWithFills ─────────────────────────────────────────────────────────────

def test_order_with_fills_empty():
    from polara.schemas.orders import Fill, OrderSide
    o = OrderWithFills(
        order_id=uuid4(),
        ib_order_id=None,
        status="pending",
        submitted_at=utcnow(),
        filled_at=None,
        fills=[],
    )
    assert o.fills == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_broker_schemas.py -v
```

Expected: `ImportError` — `polara.broker.schemas` does not exist yet.

- [ ] **Step 3: Implement broker schemas**

Create `src/polara/broker/schemas.py`:

```python
"""IB-specific Pydantic models for the broker adapter."""
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from polara.schemas.orders import Fill

# Status values that mirror the orders table CHECK constraint
OrderStatusLiteral = Literal["pending", "submitted", "filled", "cancelled", "error"]


class AccountInfo(BaseModel):
    model_config = ConfigDict(strict=True)

    net_liquidation: Decimal
    cash: Decimal
    unrealised_pnl: Decimal
    realised_pnl: Decimal
    currency: str
    timestamp: datetime  # must be UTC-aware


class Position(BaseModel):
    model_config = ConfigDict(strict=True)

    symbol: str
    quantity: Decimal
    avg_cost: Decimal
    unrealised_pnl: Decimal
    updated_at: datetime  # must be UTC-aware


class PnLSnapshot(BaseModel):
    model_config = ConfigDict(strict=True)

    net_liquidation: Decimal
    cash: Decimal
    unrealised_pnl: Decimal
    realised_pnl: Decimal
    snapshot_at: datetime  # must be UTC-aware


class BrokerStatus(BaseModel):
    model_config = ConfigDict(strict=True)

    connected: bool
    ib_server_time: datetime | None
    account_id: str | None


class OrderStatus(BaseModel):
    model_config = ConfigDict(strict=True)

    order_id: UUID
    ib_order_id: int | None
    status: OrderStatusLiteral
    submitted_at: datetime  # must be UTC-aware
    filled_at: datetime | None


class OrderWithFills(BaseModel):
    model_config = ConfigDict(strict=True)

    order_id: UUID
    ib_order_id: int | None
    status: OrderStatusLiteral
    submitted_at: datetime
    filled_at: datetime | None
    fills: list[Fill]
```

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/test_broker_schemas.py -v
```

Expected: all 11 tests pass.

- [ ] **Step 5: Lint check**

```bash
uv run ruff check src/polara/broker/schemas.py
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/polara/broker/schemas.py tests/test_broker_schemas.py
git commit -m "feat: add broker schemas (AccountInfo, Position, PnLSnapshot, BrokerStatus, OrderStatus)"
```

---

## Task 3: IBClient — connection manager

**Files:**
- Create: `src/polara/broker/client.py`

> **Note on ib_async API**: `ib_async` (asyncio fork of ib_insync) exposes an `IB` class. Core methods: `await ib.connectAsync(host, port, clientId)`, `ib.disconnect()`, `ib.isConnected()`. The `ib.connectedEvent` and `ib.disconnectedEvent` are `Event` objects you can `+=` callbacks to. Import: `from ib_async import IB`.

- [ ] **Step 1: Implement IBClient**

Create `src/polara/broker/client.py`:

```python
"""IBClient — owns the ib_async connection to IB Gateway.

Nothing outside broker/ should import from this module directly.
All external access goes through adapter.py.
"""
import asyncio
import logging
from typing import Any

from ib_async import IB

logger = logging.getLogger(__name__)

_BACKOFF_SEQUENCE = [1, 2, 4, 8, 16, 32, 60]  # seconds


class IBClient:
    """Manages a single persistent ib_async connection to IB Gateway.

    Usage (via FastAPI lifespan):
        client = IBClient(host="ib-gateway", port=4003, client_id=1)
        await client.connect()
        app.state.ib_client = client
        ...
        await client.disconnect()
    """

    def __init__(self, host: str, port: int, client_id: int) -> None:
        self._host = host
        self._port = port
        self._client_id = client_id
        self._ib = IB()
        self._reconnect_task: asyncio.Task[Any] | None = None
        self._shutdown = False

        self._ib.disconnectedEvent += self._on_disconnected

    # ── public API ─────────────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self._ib.isConnected()

    @property
    def ib(self) -> IB:
        """Raw ib_async IB instance — adapter.py only."""
        return self._ib

    async def connect(self) -> None:
        """Attempt initial connection. Logs warning and returns if unreachable."""
        self._shutdown = False
        await self._try_connect()

    async def disconnect(self) -> None:
        """Clean shutdown — cancels reconnect task then disconnects."""
        self._shutdown = True
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
        if self._ib.isConnected():
            self._ib.disconnect()
        logger.info("IBClient disconnected")

    # ── internal ───────────────────────────────────────────────────────────────

    async def _try_connect(self) -> None:
        try:
            await self._ib.connectAsync(
                host=self._host,
                port=self._port,
                clientId=self._client_id,
                timeout=10,
            )
            logger.info(
                "IBClient connected to %s:%s (clientId=%s)",
                self._host,
                self._port,
                self._client_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "IBClient could not connect to %s:%s — %s. "
                "Endpoints will return 503 until connected.",
                self._host,
                self._port,
                exc,
            )

    def _on_disconnected(self) -> None:
        if self._shutdown:
            return
        logger.warning("IBClient disconnected — scheduling reconnect")
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        for delay in _BACKOFF_SEQUENCE:
            logger.info("IBClient reconnect attempt in %ss…", delay)
            await asyncio.sleep(delay)
            if self._shutdown:
                return
            await self._try_connect()
            if self._ib.isConnected():
                logger.info("IBClient reconnected successfully")
                return
        # After exhausting sequence, keep retrying at max interval
        while not self._shutdown and not self._ib.isConnected():
            await asyncio.sleep(_BACKOFF_SEQUENCE[-1])
            if self._shutdown:
                return
            await self._try_connect()
            if self._ib.isConnected():
                logger.info("IBClient reconnected successfully")
                return
```

- [ ] **Step 2: Lint check**

```bash
uv run ruff check src/polara/broker/client.py
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add src/polara/broker/client.py
git commit -m "feat: add IBClient connection manager with exponential backoff reconnect"
```

> **Testing note:** IBClient integration tests require a live IB Gateway and are out of scope for unit tests. The adapter tests (Task 5) mock `IBClient.ib` directly.

---

## Task 4: Alembic migration `0002_broker`

**Files:**
- Create: `migrations/versions/0002_broker.py`
- Modify: `tests/test_migrations.py`

- [ ] **Step 1: Check what test_migrations.py currently looks like**

```bash
uv run pytest tests/test_migrations.py -v
```

Note the current test structure before modifying.

- [ ] **Step 2: Write the migration**

Create `migrations/versions/0002_broker.py`:

```python
"""Broker tables — orders, fills, positions, account_snapshots

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-02 00:00:00.000000
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
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
        )
    """)
    op.execute("""
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
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL UNIQUE,
            quantity TEXT NOT NULL,
            avg_cost TEXT NOT NULL,
            unrealised_pnl TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS account_snapshots (
            id TEXT PRIMARY KEY,
            net_liquidation TEXT NOT NULL,
            cash TEXT NOT NULL,
            unrealised_pnl TEXT NOT NULL,
            realised_pnl TEXT NOT NULL,
            snapshot_at TEXT NOT NULL
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS account_snapshots")
    op.execute("DROP TABLE IF EXISTS positions")
    op.execute("DROP TABLE IF EXISTS fills")
    op.execute("DROP TABLE IF EXISTS orders")
```

- [ ] **Step 3: Run the migration locally**

```bash
uv run alembic upgrade head
```

Expected: `Running upgrade 0001 -> 0002` (or just `0002` if already at 0001). No errors.

- [ ] **Step 4: Verify tables exist**

```bash
uv run python -c "
import sqlite3, pathlib
db = sqlite3.connect('data/polara.db')
tables = {r[0] for r in db.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()}
print(tables)
assert 'orders' in tables
assert 'fills' in tables
assert 'positions' in tables
assert 'account_snapshots' in tables
print('All 4 broker tables present.')
"
```

Expected: set includes the 4 new tables + original 3.

- [ ] **Step 5: Test downgrade and re-upgrade (idempotency)**

```bash
uv run alembic downgrade 0001 && uv run alembic upgrade head
```

Expected: no errors on both steps.

- [ ] **Step 6: Extend test_migrations.py**

Open `tests/test_migrations.py` and add assertions for the 4 new tables. The file follows the existing pattern (using `alembic upgrade head` + inspecting schema). Add after existing table checks:

```python
# Broker tables added in 0002
for table in ("orders", "fills", "positions", "account_snapshots"):
    assert table in tables, f"Expected table '{table}' after upgrade to 0002"
```

And add a downgrade check that verifies the 4 tables are removed:

```python
# After downgrade to 0001, broker tables must be gone
for table in ("orders", "fills", "positions", "account_snapshots"):
    assert table not in tables_after_downgrade, f"Table '{table}' should be dropped after downgrade to 0001"
```

- [ ] **Step 7: Run migration tests**

```bash
uv run pytest tests/test_migrations.py -v
```

Expected: all migration tests pass.

- [ ] **Step 8: Commit**

```bash
git add migrations/versions/0002_broker.py tests/test_migrations.py
git commit -m "feat: add migration 0002 — orders, fills, positions, account_snapshots tables"
```

---

## Task 5: BrokerAdapter — business logic

**Files:**
- Create: `src/polara/broker/adapter.py`
- Create: `tests/test_broker_adapter.py`

> **ib_async API reference used in this task:**
> - `ib.reqAccountSummaryAsync()` → list of `AccountValue` objects with `.tag`, `.value`, `.currency`
> - `ib.positions()` → list of `Position` objects with `.contract.symbol`, `.position` (float), `.avgCost` (float)
> - `ib.placeOrder(contract, order)` → `Trade` object with `.order.orderId` (int)
> - `ib.cancelOrder(order)` — cancels by order object
> - `ib.trades()` → list of `Trade` objects
> - `ib.fills()` → list of `Fill` objects with `.execution.execId`, `.execution.shares`, `.execution.price`, `.commissionReport.commission`
> - `Stock(symbol, "SMART", "USD")` → IB contract for US equities
> - `LimitOrder(action, quantity, lmtPrice)` / `MarketOrder(action, quantity)` → IB order types
> - All float values from ib_async must be converted to `Decimal` immediately

- [ ] **Step 1: Write failing adapter tests**

Create `tests/test_broker_adapter.py`:

```python
"""Tests for BrokerAdapter — ib_async client is fully mocked."""
import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from polara.broker.adapter import BrokerAdapter
from polara.broker.schemas import AccountInfo, BrokerStatus, PnLSnapshot, Position
from polara.schemas.orders import OrderRequest


def make_mock_ib_client(connected: bool = True) -> MagicMock:
    """Build a minimal mock IBClient."""
    client = MagicMock()
    client.connected = connected
    ib = MagicMock()
    ib.isConnected.return_value = connected
    client.ib = ib
    return client


def utcnow() -> datetime:
    return datetime.now(UTC)


def make_order_request() -> OrderRequest:
    return OrderRequest(
        order_id=uuid4(),
        symbol="AAPL",
        side="buy",
        quantity=Decimal("10"),
        limit_price=Decimal("150.00"),
        requested_at=utcnow(),
        strategy_id="test-strategy",
    )


# ── BrokerStatus ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_broker_status_connected():
    client = make_mock_ib_client(connected=True)
    client.ib.reqCurrentTimeAsync = AsyncMock(return_value=1000000)
    adapter = BrokerAdapter(ib_client=client, db_session_factory=AsyncMock())
    status = await adapter.get_broker_status()
    assert isinstance(status, BrokerStatus)
    assert status.connected is True


@pytest.mark.asyncio
async def test_get_broker_status_disconnected():
    client = make_mock_ib_client(connected=False)
    adapter = BrokerAdapter(ib_client=client, db_session_factory=AsyncMock())
    status = await adapter.get_broker_status()
    assert status.connected is False
    assert status.ib_server_time is None


# ── AccountInfo ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_account_disconnected_raises():
    from polara.broker.adapter import BrokerDisconnectedError
    client = make_mock_ib_client(connected=False)
    adapter = BrokerAdapter(ib_client=client, db_session_factory=AsyncMock())
    with pytest.raises(BrokerDisconnectedError):
        await adapter.get_account()


@pytest.mark.asyncio
async def test_get_account_returns_account_info():
    client = make_mock_ib_client(connected=True)

    # Mock account summary values
    def make_av(tag: str, value: str, currency: str = "USD") -> MagicMock:
        av = MagicMock()
        av.tag = tag
        av.value = value
        av.currency = currency
        return av

    client.ib.reqAccountSummaryAsync = AsyncMock(return_value=[
        make_av("NetLiquidation", "100000.00"),
        make_av("TotalCashValue", "50000.00"),
        make_av("UnrealizedPnL", "500.00"),
        make_av("RealizedPnL", "200.00"),
    ])

    adapter = BrokerAdapter(ib_client=client, db_session_factory=AsyncMock())
    info = await adapter.get_account()
    assert isinstance(info, AccountInfo)
    assert info.net_liquidation == Decimal("100000.00")
    assert info.cash == Decimal("50000.00")
    assert info.currency == "USD"


# ── Positions ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_positions_disconnected_raises():
    from polara.broker.adapter import BrokerDisconnectedError
    client = make_mock_ib_client(connected=False)
    adapter = BrokerAdapter(ib_client=client, db_session_factory=AsyncMock())
    with pytest.raises(BrokerDisconnectedError):
        await adapter.get_positions()


@pytest.mark.asyncio
async def test_get_positions_returns_list():
    client = make_mock_ib_client(connected=True)

    mock_pos = MagicMock()
    mock_pos.contract.symbol = "AAPL"
    mock_pos.position = 10.0  # ib_async returns float — adapter must convert
    mock_pos.avgCost = 150.0
    client.ib.positions.return_value = [mock_pos]

    adapter = BrokerAdapter(ib_client=client, db_session_factory=AsyncMock())
    positions = await adapter.get_positions()
    assert len(positions) == 1
    p = positions[0]
    assert isinstance(p, Position)
    assert p.symbol == "AAPL"
    assert p.quantity == Decimal("10")   # converted from float
    assert p.avg_cost == Decimal("150")  # converted from float
    assert isinstance(p.unrealised_pnl, Decimal)


# ── place_order ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_place_order_disconnected_raises():
    from polara.broker.adapter import BrokerDisconnectedError
    client = make_mock_ib_client(connected=False)
    adapter = BrokerAdapter(ib_client=client, db_session_factory=AsyncMock())
    with pytest.raises(BrokerDisconnectedError):
        await adapter.place_order(make_order_request(), db=AsyncMock())


@pytest.mark.asyncio
async def test_place_order_returns_order_id():
    client = make_mock_ib_client(connected=True)

    mock_trade = MagicMock()
    mock_trade.order.orderId = 42
    client.ib.placeOrder.return_value = mock_trade

    # Mock DB session
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    adapter = BrokerAdapter(ib_client=client, db_session_factory=AsyncMock())
    req = make_order_request()
    order_id_str = await adapter.place_order(req, db=mock_db)
    assert order_id_str == str(req.order_id)
    assert mock_db.commit.called


# ── pnl_snapshot_loop ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pnl_snapshot_loop_runs_once():
    """Verify pnl_snapshot_loop calls get_pnl_snapshot and saves to DB."""
    client = make_mock_ib_client(connected=True)

    def make_av(tag: str, value: str) -> MagicMock:
        av = MagicMock()
        av.tag = tag
        av.value = value
        av.currency = "USD"
        return av

    client.ib.reqAccountSummaryAsync = AsyncMock(return_value=[
        make_av("NetLiquidation", "100000"),
        make_av("TotalCashValue", "50000"),
        make_av("UnrealizedPnL", "500"),
        make_av("RealizedPnL", "200"),
    ])

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    adapter = BrokerAdapter(ib_client=client, db_session_factory=mock_session_factory)

    # Run one iteration of the loop (patch asyncio.sleep to exit after first call)
    call_count = 0
    async def fake_sleep(_: float) -> None:
        nonlocal call_count
        call_count += 1
        if call_count >= 1:
            raise asyncio.CancelledError

    with patch("polara.broker.adapter.asyncio.sleep", fake_sleep):
        with pytest.raises(asyncio.CancelledError):
            await adapter.pnl_snapshot_loop()

    assert mock_db.commit.called
```

- [ ] **Step 2: Run tests — expect failures**

```bash
uv run pytest tests/test_broker_adapter.py -v
```

Expected: `ImportError` — `polara.broker.adapter` not yet defined.

- [ ] **Step 3: Implement BrokerAdapter**

Create `src/polara/broker/adapter.py`:

```python
"""BrokerAdapter — business logic layer for IB Gateway communication.

All ib_async interactions happen here. Nothing else in polara/ imports ib_async.
Float values from ib_async are converted to Decimal immediately upon receipt.
"""
import asyncio
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from polara.broker.client import IBClient
from polara.broker.schemas import (
    AccountInfo,
    BrokerStatus,
    OrderStatus,
    PnLSnapshot,
    Position,
)
from polara.schemas.orders import OrderRequest

logger = logging.getLogger(__name__)

_PNL_SNAPSHOT_INTERVAL_SECONDS = 60


class BrokerDisconnectedError(RuntimeError):
    """Raised when an operation requires IB Gateway but it is not connected."""


class BrokerAdapter:
    """Business logic layer. Depends on IBClient; stores state in the DB.

    Args:
        ib_client: The IBClient instance (managed by FastAPI lifespan).
        db_session_factory: Callable that returns an async context manager
            yielding an AsyncSession (i.e. AsyncSessionLocal from db.connection).
    """

    def __init__(
        self,
        ib_client: IBClient,
        db_session_factory: Callable[[], Any],
    ) -> None:
        self._client = ib_client
        self._db_factory = db_session_factory

    # ── connection status ──────────────────────────────────────────────────────

    async def get_broker_status(self) -> BrokerStatus:
        if not self._client.connected:
            return BrokerStatus(connected=False, ib_server_time=None, account_id=None)
        try:
            epoch = await self._client.ib.reqCurrentTimeAsync()
            server_time = datetime.fromtimestamp(epoch, tz=UTC)
        except Exception:  # noqa: BLE001
            server_time = None
        return BrokerStatus(
            connected=True,
            ib_server_time=server_time,
            account_id=None,  # account_id populated via account summary if needed
        )

    # ── account ────────────────────────────────────────────────────────────────

    async def get_account(self) -> AccountInfo:
        self._require_connected()
        summary = await self._client.ib.reqAccountSummaryAsync()
        values: dict[str, str] = {}
        currency = "USD"
        for av in summary:
            values[av.tag] = av.value
            if av.tag == "NetLiquidation":
                currency = av.currency
        return AccountInfo(
            net_liquidation=Decimal(values.get("NetLiquidation", "0")),
            cash=Decimal(values.get("TotalCashValue", "0")),
            unrealised_pnl=Decimal(values.get("UnrealizedPnL", "0")),
            realised_pnl=Decimal(values.get("RealizedPnL", "0")),
            currency=currency,
            timestamp=datetime.now(UTC),
        )

    # ── positions ──────────────────────────────────────────────────────────────

    async def get_positions(self) -> list[Position]:
        self._require_connected()
        ib_positions = self._client.ib.positions()
        result: list[Position] = []
        for p in ib_positions:
            qty = Decimal(str(p.position))
            avg = Decimal(str(p.avgCost))
            # unrealised P&L not directly on Position object — compute or default 0
            unrealised = qty * avg * Decimal("0")  # placeholder; real value from account
            result.append(
                Position(
                    symbol=p.contract.symbol,
                    quantity=qty,
                    avg_cost=avg,
                    unrealised_pnl=unrealised,
                    updated_at=datetime.now(UTC),
                )
            )
        return result

    # ── orders ─────────────────────────────────────────────────────────────────

    async def place_order(self, req: OrderRequest, db: AsyncSession) -> str:
        """Submit order to IB and persist to DB. Returns order_id as string."""
        self._require_connected()
        from ib_async import LimitOrder, MarketOrder, Stock  # local import keeps ib_async isolated

        contract = Stock(req.symbol, "SMART", "USD")
        action = req.side.upper()  # "BUY" or "SELL"
        if req.limit_price is not None:
            order = LimitOrder(action, float(req.quantity), float(req.limit_price))
        else:
            order = MarketOrder(action, float(req.quantity))

        trade = self._client.ib.placeOrder(contract, order)
        ib_order_id: int | None = trade.order.orderId if trade else None

        now = datetime.now(UTC)
        row_id = str(uuid.uuid4())
        await db.execute(
            _INSERT_ORDER,
            {
                "id": row_id,
                "order_id": str(req.order_id),
                "symbol": req.symbol,
                "side": req.side,
                "quantity": str(req.quantity),
                "limit_price": str(req.limit_price) if req.limit_price else None,
                "status": "submitted",
                "ib_order_id": ib_order_id,
                "strategy_id": req.strategy_id,
                "submitted_at": now.isoformat(),
            },
        )
        await db.commit()
        logger.info("Order %s submitted (ib_order_id=%s)", req.order_id, ib_order_id)
        return str(req.order_id)

    async def cancel_order(self, order_id: str, db: AsyncSession) -> OrderStatus:
        """Cancel an open order by our order_id."""
        self._require_connected()
        from sqlalchemy import text

        row = (
            await db.execute(
                text("SELECT ib_order_id, status, submitted_at FROM orders WHERE order_id = :oid"),
                {"oid": order_id},
            )
        ).fetchone()

        if row is None:
            raise ValueError(f"Order {order_id} not found")
        if row.status in ("filled", "cancelled", "error"):
            raise ValueError(f"Cannot cancel order in status '{row.status}'")

        # Ask IB to cancel
        if row.ib_order_id is not None:
            from ib_async import Order as IBOrder
            cancel_order = IBOrder()
            cancel_order.orderId = row.ib_order_id
            self._client.ib.cancelOrder(cancel_order)

        await db.execute(
            text(
                "UPDATE orders SET status = 'cancelled' WHERE order_id = :oid"
            ),
            {"oid": order_id},
        )
        await db.commit()

        return OrderStatus(
            order_id=uuid.UUID(order_id),
            ib_order_id=row.ib_order_id,
            status="cancelled",
            submitted_at=_parse_dt(row.submitted_at),
            filled_at=None,
        )

    # ── P&L ────────────────────────────────────────────────────────────────────

    async def get_pnl_snapshot(self) -> PnLSnapshot:
        self._require_connected()
        summary = await self._client.ib.reqAccountSummaryAsync()
        values: dict[str, str] = {}
        for av in summary:
            values[av.tag] = av.value
        return PnLSnapshot(
            net_liquidation=Decimal(values.get("NetLiquidation", "0")),
            cash=Decimal(values.get("TotalCashValue", "0")),
            unrealised_pnl=Decimal(values.get("UnrealizedPnL", "0")),
            realised_pnl=Decimal(values.get("RealizedPnL", "0")),
            snapshot_at=datetime.now(UTC),
        )

    async def pnl_snapshot_loop(self) -> None:
        """Background task: snapshot P&L to DB every 60 seconds."""
        while True:
            await asyncio.sleep(_PNL_SNAPSHOT_INTERVAL_SECONDS)
            if not self._client.connected:
                continue
            try:
                snapshot = await self.get_pnl_snapshot()
                async with self._db_factory() as db:
                    await db.execute(
                        _INSERT_PNL_SNAPSHOT,
                        {
                            "id": str(uuid.uuid4()),
                            "net_liquidation": str(snapshot.net_liquidation),
                            "cash": str(snapshot.cash),
                            "unrealised_pnl": str(snapshot.unrealised_pnl),
                            "realised_pnl": str(snapshot.realised_pnl),
                            "snapshot_at": snapshot.snapshot_at.isoformat(),
                        },
                    )
                    await db.commit()
                logger.debug("P&L snapshot saved at %s", snapshot.snapshot_at)
            except Exception as exc:  # noqa: BLE001
                logger.warning("P&L snapshot failed: %s", exc)

    # ── IB callbacks ───────────────────────────────────────────────────────────

    def _register_callbacks(self) -> None:
        """Attach ib_async event handlers for fills and order status changes.

        Call this once after BrokerAdapter is constructed (done in lifespan).
        """
        self._client.ib.execDetailsEvent += self._on_exec_details
        self._client.ib.orderStatusEvent += self._on_order_status

    def _on_exec_details(self, trade: Any, fill: Any) -> None:  # type: ignore[type-arg]
        """ib_async callback — fired when a fill execution arrives."""
        asyncio.create_task(self._save_fill(fill))

    async def _save_fill(self, fill: Any) -> None:  # type: ignore[type-arg]
        """Persist a fill from IB to the fills table."""
        try:
            from sqlalchemy import text

            exec_ = fill.execution
            comm = fill.commissionReport
            async with self._db_factory() as db:
                await db.execute(
                    text("""
                        INSERT OR IGNORE INTO fills
                            (id, fill_id, order_id, symbol, side,
                             filled_quantity, fill_price, commission, filled_at)
                        VALUES
                            (:id, :fill_id, :order_id, :symbol, :side,
                             :filled_quantity, :fill_price, :commission, :filled_at)
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "fill_id": exec_.execId,
                        "order_id": exec_.orderId,  # IB orderId (int) — stored as TEXT
                        "symbol": fill.contract.symbol,
                        "side": "buy" if exec_.side == "BOT" else "sell",
                        "filled_quantity": str(Decimal(str(exec_.shares))),
                        "fill_price": str(Decimal(str(exec_.price))),
                        "commission": str(Decimal(str(comm.commission))) if comm else "0",
                        "filled_at": datetime.now(UTC).isoformat(),
                    },
                )
                # Update order status to 'filled' if fully filled
                await db.execute(
                    text(
                        "UPDATE orders SET status = 'filled', filled_at = :now "
                        "WHERE ib_order_id = :ib_oid"
                    ),
                    {"now": datetime.now(UTC).isoformat(), "ib_oid": exec_.orderId},
                )
                await db.commit()
            logger.info("Fill saved: execId=%s", exec_.execId)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to save fill: %s", exc)

    def _on_order_status(self, trade: Any) -> None:  # type: ignore[type-arg]
        """ib_async callback — fired when order status changes (e.g. submitted→filled)."""
        asyncio.create_task(self._update_order_status(trade))

    async def _update_order_status(self, trade: Any) -> None:  # type: ignore[type-arg]
        """Persist IB order status change to DB."""
        try:
            from sqlalchemy import text

            ib_status = trade.orderStatus.status  # e.g. "Submitted", "Filled", "Cancelled"
            # Map IB status strings → our status enum
            status_map = {
                "Submitted": "submitted",
                "PreSubmitted": "submitted",
                "Filled": "filled",
                "Cancelled": "cancelled",
                "Inactive": "error",
            }
            our_status = status_map.get(ib_status)
            if our_status is None:
                return  # ignore transient states like "PendingSubmit"
            async with self._db_factory() as db:
                await db.execute(
                    text(
                        "UPDATE orders SET status = :status WHERE ib_order_id = :ib_oid"
                    ),
                    {"status": our_status, "ib_oid": trade.order.orderId},
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to update order status: %s", exc)

    # ── helpers ────────────────────────────────────────────────────────────────

    def _require_connected(self) -> None:
        if not self._client.connected:
            raise BrokerDisconnectedError("IB Gateway is not connected")


# ── SQL fragments ──────────────────────────────────────────────────────────────

from sqlalchemy import text  # noqa: E402 — after class definition for readability

_INSERT_ORDER = text("""
    INSERT INTO orders
        (id, order_id, symbol, side, quantity, limit_price, status,
         ib_order_id, strategy_id, submitted_at)
    VALUES
        (:id, :order_id, :symbol, :side, :quantity, :limit_price, :status,
         :ib_order_id, :strategy_id, :submitted_at)
""")

_INSERT_PNL_SNAPSHOT = text("""
    INSERT INTO account_snapshots
        (id, net_liquidation, cash, unrealised_pnl, realised_pnl, snapshot_at)
    VALUES
        (:id, :net_liquidation, :cash, :unrealised_pnl, :realised_pnl, :snapshot_at)
""")
```

- [ ] **Step 4: Run adapter tests**

```bash
uv run pytest tests/test_broker_adapter.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Lint check**

```bash
uv run ruff check src/polara/broker/adapter.py
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/polara/broker/adapter.py tests/test_broker_adapter.py
git commit -m "feat: add BrokerAdapter with place_order, cancel_order, get_account, get_positions, pnl_snapshot_loop"
```

---

## Task 6: API routes — 8 broker endpoints

**Files:**
- Create: `src/polara/api/routes/broker.py`
- Create: `tests/test_broker_routes.py`

- [ ] **Step 1: Write failing route tests**

Create `tests/test_broker_routes.py`:

```python
"""Route-level tests for /broker/* endpoints. Adapter is fully mocked."""
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from polara.api.main import create_app
from polara.broker.adapter import BrokerAdapter, BrokerDisconnectedError
from polara.broker.schemas import (
    AccountInfo,
    BrokerStatus,
    OrderStatus,
    PnLSnapshot,
    Position,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def make_mock_adapter(connected: bool = True) -> MagicMock:
    adapter = MagicMock(spec=BrokerAdapter)
    adapter.get_broker_status = AsyncMock(
        return_value=BrokerStatus(
            connected=connected, ib_server_time=utcnow() if connected else None, account_id=None
        )
    )
    adapter.get_account = AsyncMock(
        return_value=AccountInfo(
            net_liquidation=Decimal("100000"),
            cash=Decimal("50000"),
            unrealised_pnl=Decimal("500"),
            realised_pnl=Decimal("200"),
            currency="USD",
            timestamp=utcnow(),
        )
    )
    adapter.get_positions = AsyncMock(
        return_value=[
            Position(
                symbol="AAPL",
                quantity=Decimal("10"),
                avg_cost=Decimal("150"),
                unrealised_pnl=Decimal("50"),
                updated_at=utcnow(),
            )
        ]
    )
    adapter.get_pnl_snapshot = AsyncMock(
        return_value=PnLSnapshot(
            net_liquidation=Decimal("100000"),
            cash=Decimal("50000"),
            unrealised_pnl=Decimal("500"),
            realised_pnl=Decimal("200"),
            snapshot_at=utcnow(),
        )
    )
    adapter.place_order = AsyncMock(return_value=str(uuid4()))
    adapter.cancel_order = AsyncMock(
        return_value=OrderStatus(
            order_id=uuid4(),
            ib_order_id=42,
            status="cancelled",
            submitted_at=utcnow(),
            filled_at=None,
        )
    )
    return adapter


@pytest.fixture
def app_with_mock_adapter():
    mock_adapter = make_mock_adapter()
    app = create_app()
    app.state.broker_adapter = mock_adapter
    return app, mock_adapter


@pytest.fixture
def app_disconnected():
    mock_adapter = make_mock_adapter(connected=False)
    mock_adapter.get_account = AsyncMock(side_effect=BrokerDisconnectedError("not connected"))
    mock_adapter.get_positions = AsyncMock(side_effect=BrokerDisconnectedError("not connected"))
    app = create_app()
    app.state.broker_adapter = mock_adapter
    return app


# ── GET /broker/status ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_broker_status_200(app_with_mock_adapter):
    app, _ = app_with_mock_adapter
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/broker/status")
    assert resp.status_code == 200
    assert resp.json()["connected"] is True


# ── GET /broker/account ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_broker_account_200(app_with_mock_adapter):
    app, _ = app_with_mock_adapter
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/broker/account")
    assert resp.status_code == 200
    data = resp.json()
    assert data["net_liquidation"] == "100000"
    assert data["currency"] == "USD"


@pytest.mark.asyncio
async def test_broker_account_503_when_disconnected(app_disconnected):
    async with AsyncClient(transport=ASGITransport(app=app_disconnected), base_url="http://test") as client:
        resp = await client.get("/broker/account")
    assert resp.status_code == 503


# ── GET /broker/positions ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_broker_positions_200(app_with_mock_adapter):
    app, _ = app_with_mock_adapter
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/broker/positions")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_broker_positions_503_when_disconnected(app_disconnected):
    async with AsyncClient(transport=ASGITransport(app=app_disconnected), base_url="http://test") as client:
        resp = await client.get("/broker/positions")
    assert resp.status_code == 503


# ── POST /broker/orders ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_order_201(app_with_mock_adapter):
    app, _ = app_with_mock_adapter
    payload = {
        "order_id": str(uuid4()),
        "symbol": "AAPL",
        "side": "buy",
        "quantity": "10",
        "limit_price": "150.00",
        "requested_at": utcnow().isoformat(),
        "strategy_id": "test",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/broker/orders", json=payload)
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_post_order_400_bad_payload(app_with_mock_adapter):
    app, _ = app_with_mock_adapter
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/broker/orders", json={"bad": "data"})
    assert resp.status_code == 422


# ── GET /broker/orders ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_orders_200(app_with_mock_adapter):
    app, adapter = app_with_mock_adapter
    adapter.list_orders = AsyncMock(return_value=[])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/broker/orders")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── DELETE /broker/orders/{order_id} ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_order_200(app_with_mock_adapter):
    app, _ = app_with_mock_adapter
    order_id = str(uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(f"/broker/orders/{order_id}")
    assert resp.status_code == 200


# ── GET /broker/pnl/history ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pnl_history_200(app_with_mock_adapter):
    app, adapter = app_with_mock_adapter
    adapter.list_pnl_history = AsyncMock(return_value=[])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/broker/pnl/history")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
```

- [ ] **Step 2: Run tests — expect failures**

```bash
uv run pytest tests/test_broker_routes.py -v
```

Expected: errors — routes not yet defined.

- [ ] **Step 3: Implement the broker routes**

Create `src/polara/api/routes/broker.py`:

```python
"""Broker API routes — all IB Gateway interactions proxied through BrokerAdapter."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from polara.broker.adapter import BrokerAdapter, BrokerDisconnectedError
from polara.broker.schemas import (
    AccountInfo,
    BrokerStatus,
    OrderStatus,
    OrderWithFills,
    PnLSnapshot,
    Position,
)
from polara.db.connection import get_db
from polara.schemas.orders import OrderRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/broker", tags=["broker"])


def _get_adapter(request: Request) -> BrokerAdapter:
    """FastAPI dependency — retrieves the BrokerAdapter from app.state."""
    return request.app.state.broker_adapter  # type: ignore[no-any-return]


def _disconnected(exc: BrokerDisconnectedError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=str(exc),
    )


# ── GET /broker/status ────────────────────────────────────────────────────────

@router.get("/status", response_model=BrokerStatus)
async def get_broker_status(
    adapter: BrokerAdapter = Depends(_get_adapter),
) -> BrokerStatus:
    return await adapter.get_broker_status()


# ── GET /broker/account ───────────────────────────────────────────────────────

@router.get("/account", response_model=AccountInfo)
async def get_account(
    adapter: BrokerAdapter = Depends(_get_adapter),
) -> AccountInfo:
    try:
        return await adapter.get_account()
    except BrokerDisconnectedError as exc:
        raise _disconnected(exc) from exc


# ── GET /broker/positions ─────────────────────────────────────────────────────

@router.get("/positions", response_model=list[Position])
async def get_positions(
    adapter: BrokerAdapter = Depends(_get_adapter),
) -> list[Position]:
    try:
        return await adapter.get_positions()
    except BrokerDisconnectedError as exc:
        raise _disconnected(exc) from exc


# ── POST /broker/orders ───────────────────────────────────────────────────────

@router.post("/orders", response_model=OrderStatus, status_code=status.HTTP_201_CREATED)
async def place_order(
    req: OrderRequest,
    adapter: BrokerAdapter = Depends(_get_adapter),
    db: AsyncSession = Depends(get_db),
) -> OrderStatus:
    try:
        order_id = await adapter.place_order(req, db=db)
    except BrokerDisconnectedError as exc:
        raise _disconnected(exc) from exc
    from datetime import UTC, datetime
    return OrderStatus(
        order_id=req.order_id,
        ib_order_id=None,
        status="submitted",
        submitted_at=datetime.now(UTC),
        filled_at=None,
    )


# ── GET /broker/orders ────────────────────────────────────────────────────────

@router.get("/orders", response_model=list[OrderStatus])
async def list_orders(
    adapter: BrokerAdapter = Depends(_get_adapter),
    db: AsyncSession = Depends(get_db),
) -> list[OrderStatus]:
    return await adapter.list_orders(db=db)


# ── GET /broker/orders/{order_id} ─────────────────────────────────────────────

@router.get("/orders/{order_id}", response_model=OrderWithFills)
async def get_order(
    order_id: str,
    adapter: BrokerAdapter = Depends(_get_adapter),
    db: AsyncSession = Depends(get_db),
) -> OrderWithFills:
    result = await adapter.get_order_with_fills(order_id=order_id, db=db)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return result


# ── DELETE /broker/orders/{order_id} ─────────────────────────────────────────

@router.delete("/orders/{order_id}", response_model=OrderStatus)
async def cancel_order(
    order_id: str,
    adapter: BrokerAdapter = Depends(_get_adapter),
    db: AsyncSession = Depends(get_db),
) -> OrderStatus:
    try:
        return await adapter.cancel_order(order_id=order_id, db=db)
    except BrokerDisconnectedError as exc:
        raise _disconnected(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


# ── GET /broker/pnl/history ───────────────────────────────────────────────────

@router.get("/pnl/history", response_model=list[PnLSnapshot])
async def pnl_history(
    adapter: BrokerAdapter = Depends(_get_adapter),
    db: AsyncSession = Depends(get_db),
) -> list[PnLSnapshot]:
    return await adapter.list_pnl_history(db=db)
```

- [ ] **Step 4: Add `list_orders`, `get_order_with_fills`, `list_pnl_history` to adapter.py**

Append to `src/polara/broker/adapter.py` (inside the `BrokerAdapter` class, before `_require_connected`):

```python
    async def list_orders(self, db: AsyncSession) -> list[OrderStatus]:
        from sqlalchemy import text
        from uuid import UUID

        rows = (
            await db.execute(text("SELECT order_id, ib_order_id, status, submitted_at, filled_at FROM orders ORDER BY submitted_at DESC"))
        ).fetchall()
        result = []
        for row in rows:
            result.append(OrderStatus(
                order_id=UUID(row.order_id),
                ib_order_id=row.ib_order_id,
                status=row.status,
                submitted_at=_parse_dt(row.submitted_at),
                filled_at=_parse_dt(row.filled_at) if row.filled_at else None,
            ))
        return result

    async def get_order_with_fills(self, order_id: str, db: AsyncSession) -> OrderWithFills | None:
        from sqlalchemy import text
        from uuid import UUID
        from polara.schemas.orders import Fill, OrderSide

        order_row = (
            await db.execute(
                text("SELECT order_id, ib_order_id, status, submitted_at, filled_at FROM orders WHERE order_id = :oid"),
                {"oid": order_id},
            )
        ).fetchone()
        if order_row is None:
            return None

        fill_rows = (
            await db.execute(
                text("SELECT fill_id, order_id, symbol, side, filled_quantity, fill_price, commission, filled_at FROM fills WHERE order_id = :oid"),
                {"oid": order_id},
            )
        ).fetchall()

        fills = [
            Fill(
                fill_id=UUID(r.fill_id),
                order_id=UUID(r.order_id),
                symbol=r.symbol,
                side=r.side,
                filled_quantity=Decimal(r.filled_quantity),
                fill_price=Decimal(r.fill_price),
                commission=Decimal(r.commission),
                filled_at=_parse_dt(r.filled_at),
            )
            for r in fill_rows
        ]

        return OrderWithFills(
            order_id=UUID(order_row.order_id),
            ib_order_id=order_row.ib_order_id,
            status=order_row.status,
            submitted_at=_parse_dt(order_row.submitted_at),
            filled_at=_parse_dt(order_row.filled_at) if order_row.filled_at else None,
            fills=fills,
        )

    async def list_pnl_history(self, db: AsyncSession) -> list[PnLSnapshot]:
        from sqlalchemy import text

        rows = (
            await db.execute(
                text("SELECT net_liquidation, cash, unrealised_pnl, realised_pnl, snapshot_at FROM account_snapshots ORDER BY snapshot_at DESC")
            )
        ).fetchall()
        return [
            PnLSnapshot(
                net_liquidation=Decimal(r.net_liquidation),
                cash=Decimal(r.cash),
                unrealised_pnl=Decimal(r.unrealised_pnl),
                realised_pnl=Decimal(r.realised_pnl),
                snapshot_at=_parse_dt(r.snapshot_at),
            )
            for r in rows
        ]
```

Also add the `_parse_dt` helper function at module level in `adapter.py` (after the class):

```python
def _parse_dt(value: str) -> datetime:
    """Parse an ISO 8601 UTC string from DB into a UTC-aware datetime."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt
```

- [ ] **Step 5: Run route tests**

```bash
uv run pytest tests/test_broker_routes.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Lint**

```bash
uv run ruff check src/polara/api/routes/broker.py src/polara/broker/adapter.py
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/polara/api/routes/broker.py src/polara/broker/adapter.py tests/test_broker_routes.py
git commit -m "feat: add broker API routes (8 endpoints) and list_orders/get_order_with_fills/list_pnl_history on adapter"
```

---

## Task 7: Wire everything together — lifespan + docker-compose

**Files:**
- Modify: `src/polara/api/main.py`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Update main.py lifespan**

Replace the contents of `src/polara/api/main.py` with:

```python
import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from polara.api.routes.broker import router as broker_router
from polara.api.routes.health import router as health_router
from polara.broker.adapter import BrokerAdapter
from polara.broker.client import IBClient
from polara.db.connection import DATABASE_URL, AsyncSessionLocal

logger = logging.getLogger(__name__)

IB_HOST = os.getenv("IB_HOST", "ib-gateway")
IB_PORT = int(os.getenv("IB_PORT", "4003"))
IB_CLIENT_ID = int(os.getenv("IB_CLIENT_ID", "1"))


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    masked = _mask_db_url(DATABASE_URL)
    logger.info("Polara Quant %s starting — DB: %s", _get_version(), masked)

    # Start IB Gateway connection (non-blocking — will retry in background if unreachable)
    ib_client = IBClient(host=IB_HOST, port=IB_PORT, client_id=IB_CLIENT_ID)
    await ib_client.connect()
    app.state.ib_client = ib_client

    # Build adapter (injected into routes via app.state)
    adapter = BrokerAdapter(ib_client=ib_client, db_session_factory=AsyncSessionLocal)
    adapter._register_callbacks()  # attach fill + order status event handlers
    app.state.broker_adapter = adapter

    # Start P&L snapshot background task
    pnl_task = asyncio.create_task(adapter.pnl_snapshot_loop())
    app.state.pnl_task = pnl_task

    yield

    # Shutdown
    pnl_task.cancel()
    try:
        await pnl_task
    except asyncio.CancelledError:
        pass
    await ib_client.disconnect()
    logger.info("Polara Quant %s stopped", _get_version())


def create_app() -> FastAPI:
    app = FastAPI(title="Polara Quant", version=_get_version(), lifespan=_lifespan)

    app.include_router(health_router)
    app.include_router(broker_router)

    return app


def _mask_db_url(url: str) -> str:
    """Mask credentials in DB URL for safe logging."""
    if "@" in url:
        scheme, rest = url.split("://", 1)
        host_part = rest.split("@", 1)[1]
        return f"{scheme}://***@{host_part}"
    return url


def _get_version() -> str:
    from polara import __version__

    return __version__


# Module-level app instance for uvicorn
app = create_app()
```

- [ ] **Step 2: Run existing test suite — verify nothing broken**

```bash
uv run pytest tests/ -v --ignore=tests/test_broker_routes.py
```

Expected: health tests and schema tests still pass. The broker route tests that mock `app.state.broker_adapter` should also pass because `create_app()` sets up lifespan but the tests override `app.state` directly.

- [ ] **Step 3: Update docker-compose.yml**

Replace `docker-compose.yml` with:

```yaml
services:
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
      - "4003:4003"
    volumes:
      - ./data/jts:/home/ibgateway/Jts

  polara-api:
    build:
      context: .
      dockerfile: docker/Dockerfile
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
    environment:
      - DATABASE_URL=sqlite+aiosqlite:///./data/polara.db
      - IB_HOST=ib-gateway
      - IB_PORT=4003
      - IB_CLIENT_ID=1
    depends_on:
      - ib-gateway
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 30s
```

- [ ] **Step 4: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 5: Lint all changed files**

```bash
uv run ruff check src/
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/polara/api/main.py docker-compose.yml
git commit -m "feat: wire IBClient + BrokerAdapter into FastAPI lifespan; add ib-gateway to docker-compose"
```

---

## Task 8: Update CLAUDE.md phase status

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the phase marker in CLAUDE.md**

Change the phase section from:

```
## Phase Status
Current phase: Phase 0-1 (Foundation)
Do NOT build: broker_adapter, order_manager, risk_guard, research_engine, validator
These are Phase 2+ work.
```

To:

```
## Phase Status
Current phase: Phase 2 (Broker Adapter)
Do NOT build: order_manager, risk_guard, research_engine, validator, market_data_streaming
These are Phase 3+ work.
```

- [ ] **Step 2: Run full test suite one final time**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 3: Final lint**

```bash
uv run ruff check src/
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "chore: update CLAUDE.md phase status to Phase 2"
```

---

## Phase 2 Exit Criteria Checklist

After deploying to the VM (`git pull && docker compose up --build -d`), verify:

- [ ] `GET /broker/status` returns `{"connected": true, ...}`
- [ ] `POST /broker/orders` submits a paper order and returns `201`
- [ ] `GET /broker/account` returns real account values with Decimal precision (as strings in JSON)
- [ ] `GET /broker/positions` reflects actual paper positions
- [ ] `DELETE /broker/orders/{id}` cancels an open order
- [ ] `GET /broker/pnl/history` returns at least one snapshot after 60 seconds
- [ ] All tests pass: `uv run pytest tests/ -v`
- [ ] No floats in broker module: `uv run ruff check src/`
- [ ] IB Gateway auto-reconnects after `docker compose restart ib-gateway`
