# Phase 6: Bracket Orders, Stop-Loss / Take-Profit, and Delta-Aware Sizing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add IB bracket orders (stop-loss + take-profit) to the order pipeline, and replace full-quantity ordering with delta-aware sizing that tracks in-flight orders to prevent overshooting `max_position_pct`.

**Architecture:** `Signal` gains optional `stop_loss_pct` / `take_profit_pct` percentage fields; `OrderManager` converts these to absolute prices and routes to a new `BrokerAdapter.place_bracket_order` method that submits three linked IB orders (parent market + stop child + take-profit child). An in-memory `_pending` dict on `OrderManager` tracks submitted-but-unfilled quantities; `_compute_delta` subtracts held + in-flight from the target quantity before submitting.

**Tech Stack:** Python 3.12+, pydantic v2 (`strict=True`), ib_async (bracket via `StopOrder` / `LimitOrder` with `parentId`), SQLAlchemy async (`text()`), aiosqlite, Alembic, pytest-asyncio, `Decimal` / `ROUND_DOWN` / `ROUND_UP`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `src/polara/schemas/signals.py` | Add `stop_loss_pct`, `take_profit_pct` fields + float validators |
| Create | `migrations/versions/0005_phase6.py` | `bracket_orders` table; nullable cols on `signal_orders` |
| Modify | `src/polara/broker/adapter.py` | Add `place_bracket_order` method + `_INSERT_BRACKET_ORDER` SQL |
| Modify | `src/polara/order_manager/manager.py` | `_pending` dict; `_reconcile_pending`; `_compute_delta`; `_compute_exit_prices`; updated `process_signal` |
| Modify | `src/polara/research_engine/strategies/ma_crossover.py` | Optional `stop_loss_pct` / `take_profit_pct` dataclass fields |
| Modify | `src/polara/research_engine/strategies/rsi_mean_reversion.py` | Same |
| Modify | `src/polara/api/main.py` | Wire env vars for strategy stop/take-profit params |
| Modify | `tests/test_schemas.py` | 6 new Signal exit-param tests |
| Modify | `tests/test_migrations.py` | 3 new Phase 6 migration tests |
| Modify | `tests/test_broker_adapter.py` | 6 new bracket order tests |
| Create | `tests/test_exit_prices.py` | 7 unit tests for `_compute_exit_prices` |
| Modify | `tests/test_order_manager.py` | 11 new delta sizing + bracket routing tests |

---

## Task 1: Signal schema — add stop_loss_pct and take_profit_pct

**Files:**
- Modify: `src/polara/schemas/signals.py`
- Modify: `tests/test_schemas.py`

- [ ] **Step 1: Write 6 failing tests in `tests/test_schemas.py`**

Find the existing Signal test block (search for `test_signal_reference_price`) and add after the last Signal test:

```python
def test_signal_stop_loss_pct_defaults_to_none() -> None:
    sig = Signal(
        signal_id=uuid4(),
        strategy_id="s1",
        symbol="AAPL",
        strength=Decimal("0.5"),
        generated_at=datetime.now(UTC),
    )
    assert sig.stop_loss_pct is None


def test_signal_take_profit_pct_defaults_to_none() -> None:
    sig = Signal(
        signal_id=uuid4(),
        strategy_id="s1",
        symbol="AAPL",
        strength=Decimal("0.5"),
        generated_at=datetime.now(UTC),
    )
    assert sig.take_profit_pct is None


def test_signal_stop_loss_pct_accepts_decimal() -> None:
    sig = Signal(
        signal_id=uuid4(),
        strategy_id="s1",
        symbol="AAPL",
        strength=Decimal("0.5"),
        generated_at=datetime.now(UTC),
        stop_loss_pct=Decimal("5"),
    )
    assert sig.stop_loss_pct == Decimal("5")


def test_signal_take_profit_pct_accepts_decimal() -> None:
    sig = Signal(
        signal_id=uuid4(),
        strategy_id="s1",
        symbol="AAPL",
        strength=Decimal("0.5"),
        generated_at=datetime.now(UTC),
        take_profit_pct=Decimal("10"),
    )
    assert sig.take_profit_pct == Decimal("10")


def test_signal_stop_loss_pct_rejects_float() -> None:
    with pytest.raises(ValidationError):
        Signal(
            signal_id=uuid4(),
            strategy_id="s1",
            symbol="AAPL",
            strength=Decimal("0.5"),
            generated_at=datetime.now(UTC),
            stop_loss_pct=5.0,
        )


def test_signal_take_profit_pct_rejects_float() -> None:
    with pytest.raises(ValidationError):
        Signal(
            signal_id=uuid4(),
            strategy_id="s1",
            symbol="AAPL",
            strength=Decimal("0.5"),
            generated_at=datetime.now(UTC),
            take_profit_pct=10.0,
        )
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd /Users/cgncn/polara_quant/.claude/worktrees/pedantic-wilbur
uv run pytest tests/test_schemas.py -k "stop_loss_pct or take_profit_pct" -v
```

Expected: 6 FAILs with `AttributeError` / `TypeError`

- [ ] **Step 3: Add the fields and validators to `src/polara/schemas/signals.py`**

The file currently ends at `reference_price` and its `reject_float_price` validator. Add after line 28 (after the `reject_float_price` validator), before the `generated_at` validator:

```python
    stop_loss_pct: Decimal | None = None
    take_profit_pct: Decimal | None = None

    @field_validator("stop_loss_pct", "take_profit_pct", mode="before")
    @classmethod
    def reject_float_pct(cls, v: object) -> object:
        if isinstance(v, float):
            raise ValueError("stop_loss_pct and take_profit_pct must be Decimal, not float")
        return v
```

The complete updated `Signal` class fields section (from `signal_id` through the new fields) should read:

```python
class Signal(BaseModel):
    model_config = ConfigDict(strict=True)

    signal_id: UUID
    strategy_id: str
    symbol: str
    strength: Decimal
    generated_at: datetime
    reference_price: Decimal | None = None
    stop_loss_pct: Decimal | None = None
    take_profit_pct: Decimal | None = None

    @field_validator("reference_price", mode="before")
    @classmethod
    def reject_float_price(cls, v: object) -> object:
        if isinstance(v, float):
            raise ValueError("reference_price must be Decimal, not float")
        return v

    @field_validator("stop_loss_pct", "take_profit_pct", mode="before")
    @classmethod
    def reject_float_pct(cls, v: object) -> object:
        if isinstance(v, float):
            raise ValueError("stop_loss_pct and take_profit_pct must be Decimal, not float")
        return v

    @field_validator("generated_at", mode="after")
    @classmethod
    def generated_at_must_be_utc(cls, v: datetime) -> datetime:
        return validate_utc_datetime(v)

    @field_validator("strength", mode="before")
    @classmethod
    def reject_float(cls, v: object) -> object:
        if isinstance(v, float):
            raise ValueError("float is not allowed for strength; use Decimal")
        return v

    @field_validator("strength", mode="after")
    @classmethod
    def strength_in_range(cls, v: Decimal) -> Decimal:
        if v < _MINUS_ONE or v > _ONE:
            raise ValueError(f"strength must be in range [-1, 1], got {v}")
        return v
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd /Users/cgncn/polara_quant/.claude/worktrees/pedantic-wilbur
uv run pytest tests/test_schemas.py -v
```

Expected: all tests PASS (34+ tests)

- [ ] **Step 5: Run ruff**

```bash
cd /Users/cgncn/polara_quant/.claude/worktrees/pedantic-wilbur
uv run ruff check src/
```

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
cd /Users/cgncn/polara_quant/.claude/worktrees/pedantic-wilbur
git add src/polara/schemas/signals.py tests/test_schemas.py
git commit -m "feat: add stop_loss_pct and take_profit_pct to Signal"
```

---

## Task 2: Migration 0005 — bracket_orders table + signal_orders columns

**Files:**
- Create: `migrations/versions/0005_phase6.py`
- Modify: `tests/test_migrations.py`

- [ ] **Step 1: Write 3 failing migration tests in `tests/test_migrations.py`**

Add to the end of the file (the existing `_alembic_cfg` and `_get_tables` helpers are already there):

```python
async def _get_columns(db_url: str, table: str) -> list[str]:
    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        cols = await conn.run_sync(
            lambda sync_conn: [
                c["name"] for c in inspect(sync_conn).get_columns(table)
            ]
        )
    await engine.dispose()
    return cols


def test_0005_bracket_orders_table_created() -> None:
    original = os.environ.get("DATABASE_URL")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        cfg = _alembic_cfg(db_path)
        command.upgrade(cfg, "head")
        tables = asyncio.run(_get_tables(f"sqlite+aiosqlite:///{db_path}"))
        assert "bracket_orders" in tables
    finally:
        os.unlink(db_path)
        if original is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original


def test_0005_signal_orders_has_stop_price_column() -> None:
    original = os.environ.get("DATABASE_URL")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        cfg = _alembic_cfg(db_path)
        command.upgrade(cfg, "head")
        cols = asyncio.run(
            _get_columns(f"sqlite+aiosqlite:///{db_path}", "signal_orders")
        )
        assert "stop_price" in cols
        assert "take_profit_price" in cols
    finally:
        os.unlink(db_path)
        if original is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original


def test_0005_downgrade_removes_bracket_orders() -> None:
    original = os.environ.get("DATABASE_URL")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        cfg = _alembic_cfg(db_path)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0004")
        tables = asyncio.run(_get_tables(f"sqlite+aiosqlite:///{db_path}"))
        assert "bracket_orders" not in tables
    finally:
        os.unlink(db_path)
        if original is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd /Users/cgncn/polara_quant/.claude/worktrees/pedantic-wilbur
uv run pytest tests/test_migrations.py -k "0005" -v
```

Expected: 3 FAILs

- [ ] **Step 3: Create `migrations/versions/0005_phase6.py`**

```python
"""Phase 6: bracket_orders table; stop_price/take_profit_price cols on signal_orders

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-04
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # New table: bracket_orders — stores stop/take-profit child IB order IDs
    op.create_table(
        "bracket_orders",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("order_id", sa.Text, nullable=False),
        sa.Column("stop_ib_id", sa.Integer, nullable=True),
        sa.Column("take_profit_ib_id", sa.Integer, nullable=True),
        sa.Column("stop_price", sa.Text, nullable=True),
        sa.Column("take_profit_price", sa.Text, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index(
        "ix_bracket_orders_order_id", "bracket_orders", ["order_id"]
    )

    # Add nullable audit columns to signal_orders.
    # SQLite supports ADD COLUMN natively for nullable columns.
    op.add_column("signal_orders", sa.Column("stop_price", sa.Text, nullable=True))
    op.add_column(
        "signal_orders", sa.Column("take_profit_price", sa.Text, nullable=True)
    )


def downgrade() -> None:
    op.drop_index("ix_bracket_orders_order_id", "bracket_orders")
    op.drop_table("bracket_orders")

    # SQLite < 3.35 does not support DROP COLUMN — recreate signal_orders without
    # the Phase 6 columns using the same CREATE/INSERT/DROP/RENAME pattern.
    op.execute("""
        CREATE TABLE signal_orders_old (
            id            TEXT PRIMARY KEY,
            signal_id     TEXT NOT NULL,
            order_id      TEXT NOT NULL,
            strategy_id   TEXT NOT NULL,
            symbol        TEXT NOT NULL,
            signal_strength TEXT NOT NULL,
            created_at    TEXT NOT NULL
        )
    """)
    op.execute("""
        INSERT INTO signal_orders_old
            (id, signal_id, order_id, strategy_id, symbol, signal_strength, created_at)
        SELECT id, signal_id, order_id, strategy_id, symbol, signal_strength, created_at
        FROM signal_orders
    """)
    op.execute("DROP TABLE signal_orders")
    op.execute("ALTER TABLE signal_orders_old RENAME TO signal_orders")
```

- [ ] **Step 4: Run migration tests**

```bash
cd /Users/cgncn/polara_quant/.claude/worktrees/pedantic-wilbur
uv run pytest tests/test_migrations.py -v
```

Expected: all PASS

- [ ] **Step 5: Verify migration applies cleanly**

```bash
cd /Users/cgncn/polara_quant/.claude/worktrees/pedantic-wilbur
uv run alembic upgrade head
```

Expected: runs without error

- [ ] **Step 6: Commit**

```bash
cd /Users/cgncn/polara_quant/.claude/worktrees/pedantic-wilbur
git add migrations/versions/0005_phase6.py tests/test_migrations.py
git commit -m "feat: migration 0005 — bracket_orders table and signal_orders exit price columns"
```

---

## Task 3: BrokerAdapter — place_bracket_order

**Files:**
- Modify: `src/polara/broker/adapter.py`
- Modify: `tests/test_broker_adapter.py` (create if it does not exist)

**Background:** IB bracket orders require three linked `placeOrder` calls. The parent order uses `transmit=False`; all children except the last also use `transmit=False`; the final child uses `transmit=True` to atomically submit the whole bracket. Children reference the parent via `parentId`. We obtain the parent's IB order ID synchronously with `ib.client.getReqId()` before placing.

- [ ] **Step 1: Write 6 failing tests**

If `tests/test_broker_adapter.py` does not exist, create it. If it exists, append to it. Add:

```python
"""Tests for BrokerAdapter.place_bracket_order."""
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import uuid4

import pytest

from polara.broker.adapter import BrokerAdapter
from polara.schemas.orders import OrderRequest


def make_order_req(side: str = "buy") -> OrderRequest:
    return OrderRequest(
        order_id=uuid4(),
        symbol="AAPL",
        side=side,
        quantity=Decimal("100"),
        limit_price=None,
        requested_at=datetime.now(UTC),
        strategy_id="test-strategy",
    )


def make_adapter():
    client = MagicMock()
    client.connected = True
    client.ib.client.getReqId.return_value = 42

    # Each placeOrder call returns a mock trade with an orderId
    def _place_order_side_effect(contract, order):
        trade = MagicMock()
        trade.order.orderId = order.orderId if order.orderId else 99
        return trade

    client.ib.placeOrder.side_effect = _place_order_side_effect

    db_factory = MagicMock()
    db_session = AsyncMock()
    db_session.execute = AsyncMock()
    db_session.commit = AsyncMock()
    db_session.__aenter__ = AsyncMock(return_value=db_session)
    db_session.__aexit__ = AsyncMock(return_value=None)

    return BrokerAdapter(ib_client=client, db_session_factory=db_factory), client, db_session


@pytest.mark.asyncio
async def test_place_bracket_order_submits_three_ib_orders():
    adapter, client, db = make_adapter()
    req = make_order_req("buy")
    await adapter.place_bracket_order(
        req, stop_price=Decimal("95.00"), take_profit_price=Decimal("110.00"), db=db
    )
    assert client.ib.placeOrder.call_count == 3


@pytest.mark.asyncio
async def test_bracket_parent_transmit_false():
    adapter, client, db = make_adapter()
    req = make_order_req("buy")
    await adapter.place_bracket_order(
        req, stop_price=Decimal("95.00"), take_profit_price=Decimal("110.00"), db=db
    )
    parent_order = client.ib.placeOrder.call_args_list[0][0][1]
    assert parent_order.transmit is False


@pytest.mark.asyncio
async def test_bracket_last_child_transmit_true():
    adapter, client, db = make_adapter()
    req = make_order_req("buy")
    await adapter.place_bracket_order(
        req, stop_price=Decimal("95.00"), take_profit_price=Decimal("110.00"), db=db
    )
    last_order = client.ib.placeOrder.call_args_list[2][0][1]
    assert last_order.transmit is True


@pytest.mark.asyncio
async def test_bracket_children_have_correct_parent_id():
    adapter, client, db = make_adapter()
    req = make_order_req("buy")
    await adapter.place_bracket_order(
        req, stop_price=Decimal("95.00"), take_profit_price=Decimal("110.00"), db=db
    )
    stop_order = client.ib.placeOrder.call_args_list[1][0][1]
    tp_order = client.ib.placeOrder.call_args_list[2][0][1]
    assert stop_order.parentId == 42
    assert tp_order.parentId == 42


@pytest.mark.asyncio
async def test_bracket_stop_is_sell_for_buy_parent():
    adapter, client, db = make_adapter()
    req = make_order_req("buy")
    await adapter.place_bracket_order(
        req, stop_price=Decimal("95.00"), take_profit_price=Decimal("110.00"), db=db
    )
    stop_order = client.ib.placeOrder.call_args_list[1][0][1]
    assert stop_order.action == "SELL"


@pytest.mark.asyncio
async def test_bracket_stop_is_buy_for_sell_parent():
    adapter, client, db = make_adapter()
    req = make_order_req("sell")
    await adapter.place_bracket_order(
        req, stop_price=Decimal("105.00"), take_profit_price=Decimal("90.00"), db=db
    )
    stop_order = client.ib.placeOrder.call_args_list[1][0][1]
    assert stop_order.action == "BUY"
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd /Users/cgncn/polara_quant/.claude/worktrees/pedantic-wilbur
uv run pytest tests/test_broker_adapter.py -k "bracket" -v
```

Expected: 6 FAILs with `AttributeError: 'BrokerAdapter' object has no attribute 'place_bracket_order'`

- [ ] **Step 3: Add `_INSERT_BRACKET_ORDER` SQL constant and `place_bracket_order` to `src/polara/broker/adapter.py`**

Add the SQL constant after `_UPSERT_POSITION` (around line 57):

```python
_INSERT_BRACKET_ORDER = text("""
    INSERT INTO bracket_orders
        (id, order_id, stop_ib_id, take_profit_ib_id, stop_price, take_profit_price, created_at)
    VALUES
        (:id, :order_id, :stop_ib_id, :take_profit_ib_id, :stop_price, :take_profit_price, :created_at)
""")
```

Add the `place_bracket_order` method to `BrokerAdapter` after `place_order` (after line 187):

```python
async def place_bracket_order(
    self,
    req: OrderRequest,
    stop_price: Decimal | None,
    take_profit_price: Decimal | None,
    db: AsyncSession,
) -> str:
    """Submit a bracket order (parent market + stop child + take-profit child).

    IB requires transmit=False on all orders except the last child, which uses
    transmit=True to atomically submit the entire bracket.
    Returns the parent order_id as a string.
    """
    self._require_connected()
    from ib_async import LimitOrder, MarketOrder, Stock, StopOrder  # noqa: PLC0415

    contract = Stock(req.symbol, "SMART", "USD")
    action = req.side.upper()
    opposite = "SELL" if action == "BUY" else "BUY"
    qty = float(req.quantity)

    # Reserve a parent order ID before creating children (they need parentId set).
    parent_id = self._client.ib.client.getReqId()

    parent = MarketOrder(action, qty, transmit=False)
    parent.orderId = parent_id

    # Build child orders; last one gets transmit=True.
    children: list[object] = []
    if stop_price is not None:
        stop = StopOrder(
            opposite, qty, float(stop_price), parentId=parent_id, transmit=False
        )
        children.append(stop)
    if take_profit_price is not None:
        tp = LimitOrder(
            opposite, qty, float(take_profit_price), parentId=parent_id, transmit=False
        )
        children.append(tp)

    if children:
        children[-1].transmit = True  # type: ignore[attr-defined]
    else:
        parent.transmit = True  # no children — transmit parent immediately

    parent_trade = self._client.ib.placeOrder(contract, parent)
    ib_order_id: int | None = parent_trade.order.orderId if parent_trade else None

    stop_ib_id: int | None = None
    tp_ib_id: int | None = None
    for i, child in enumerate(children):
        child_trade = self._client.ib.placeOrder(contract, child)
        child_ib_id = child_trade.order.orderId if child_trade else None
        if stop_price is not None and i == 0:
            stop_ib_id = child_ib_id
        else:
            tp_ib_id = child_ib_id

    now = datetime.now(UTC)
    await db.execute(
        _INSERT_ORDER,
        {
            "id": str(uuid.uuid4()),
            "order_id": str(req.order_id),
            "symbol": req.symbol,
            "side": req.side,
            "quantity": str(req.quantity),
            "limit_price": None,
            "status": "submitted",
            "ib_order_id": ib_order_id,
            "strategy_id": req.strategy_id,
            "submitted_at": now.isoformat(),
        },
    )
    await db.execute(
        _INSERT_BRACKET_ORDER,
        {
            "id": str(uuid.uuid4()),
            "order_id": str(req.order_id),
            "stop_ib_id": stop_ib_id,
            "take_profit_ib_id": tp_ib_id,
            "stop_price": str(stop_price) if stop_price is not None else None,
            "take_profit_price": (
                str(take_profit_price) if take_profit_price is not None else None
            ),
            "created_at": now.isoformat(),
        },
    )
    await db.commit()
    logger.info(
        "Bracket order %s submitted (parent_ib_id=%s, stop=%s, tp=%s)",
        req.order_id, ib_order_id, stop_price, take_profit_price,
    )
    return str(req.order_id)
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/cgncn/polara_quant/.claude/worktrees/pedantic-wilbur
uv run pytest tests/test_broker_adapter.py -v
```

Expected: all bracket tests PASS

- [ ] **Step 5: Run full suite**

```bash
cd /Users/cgncn/polara_quant/.claude/worktrees/pedantic-wilbur
uv run pytest
```

Expected: all PASS

- [ ] **Step 6: Ruff**

```bash
cd /Users/cgncn/polara_quant/.claude/worktrees/pedantic-wilbur
uv run ruff check src/
```

Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
cd /Users/cgncn/polara_quant/.claude/worktrees/pedantic-wilbur
git add src/polara/broker/adapter.py tests/test_broker_adapter.py
git commit -m "feat: add place_bracket_order to BrokerAdapter"
```

---

## Task 4: OrderManager — _pending tracker, _reconcile_pending, _compute_delta

**Files:**
- Modify: `src/polara/order_manager/manager.py`
- Modify: `tests/test_order_manager.py`

**Background:** `_pending` is a `dict[str, Decimal]` mapping symbol → quantity of shares submitted but not yet reflected in live position data. On each `process_signal` call, after fetching positions, we reconcile (clear entries where held >= pending). We compute delta = target − held − in_flight, and only order the delta.

- [ ] **Step 1: Write 7 failing tests in `tests/test_order_manager.py`**

Append after the existing dynamic sizing tests:

```python
# ---------------------------------------------------------------------------
# Delta sizing and pending tracker tests
# ---------------------------------------------------------------------------

def make_position(symbol: str, quantity: Decimal) -> Position:
    return Position(
        symbol=symbol,
        quantity=quantity,
        avg_cost=Decimal("50"),
        unrealised_pnl=Decimal("0"),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_delta_sizing_no_pending_no_position():
    """First signal, no position held, nothing in-flight → orders full target qty."""
    adapter = make_mock_adapter(
        account=make_account_with_nav(Decimal("100000")),
        positions=[],
    )
    guard = RiskGuard(max_position_pct=Decimal("10"), max_daily_loss_pct=Decimal("5"))
    db_factory, _ = make_mock_db_session()
    manager = OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=make_mock_status_service("live"),
    )
    signal = make_signal_with_price(strength="1", reference_price=Decimal("50"))
    await manager.process_signal(signal)

    req = adapter.place_order.call_args[0][0]
    assert req.quantity == Decimal("200")  # floor(100000*10%*1/50)


@pytest.mark.asyncio
async def test_delta_sizing_with_pending():
    """100 shares in-flight → orders only delta (200 - 100 = 100)."""
    adapter = make_mock_adapter(
        account=make_account_with_nav(Decimal("100000")),
        positions=[],
    )
    guard = RiskGuard(max_position_pct=Decimal("10"), max_daily_loss_pct=Decimal("5"))
    db_factory, _ = make_mock_db_session()
    manager = OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=make_mock_status_service("live"),
    )
    # Simulate 100 shares already in-flight
    manager._pending["AAPL"] = Decimal("100")

    signal = make_signal_with_price(strength="1", reference_price=Decimal("50"))
    await manager.process_signal(signal)

    req = adapter.place_order.call_args[0][0]
    assert req.quantity == Decimal("100")


@pytest.mark.asyncio
async def test_delta_sizing_with_held_position():
    """150 shares already held → orders only delta (200 - 150 = 50)."""
    adapter = make_mock_adapter(
        account=make_account_with_nav(Decimal("100000")),
        positions=[make_position("AAPL", Decimal("150"))],
    )
    guard = RiskGuard(max_position_pct=Decimal("10"), max_daily_loss_pct=Decimal("5"))
    db_factory, _ = make_mock_db_session()
    manager = OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=make_mock_status_service("live"),
    )
    signal = make_signal_with_price(strength="1", reference_price=Decimal("50"))
    await manager.process_signal(signal)

    req = adapter.place_order.call_args[0][0]
    assert req.quantity == Decimal("50")


@pytest.mark.asyncio
async def test_delta_sizing_already_at_target_skips_signal():
    """held(200) + pending(0) >= target(200) → delta=0 → signal skipped."""
    adapter = make_mock_adapter(
        account=make_account_with_nav(Decimal("100000")),
        positions=[make_position("AAPL", Decimal("200"))],
    )
    guard = RiskGuard(max_position_pct=Decimal("10"), max_daily_loss_pct=Decimal("5"))
    db_factory, _ = make_mock_db_session()
    manager = OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=make_mock_status_service("live"),
    )
    signal = make_signal_with_price(strength="1", reference_price=Decimal("50"))
    result = await manager.process_signal(signal)

    assert result is None
    adapter.place_order.assert_not_called()


@pytest.mark.asyncio
async def test_pending_reconciliation_clears_on_fill():
    """Once positions show held >= pending, the pending entry is cleared."""
    adapter = make_mock_adapter(
        account=make_account_with_nav(Decimal("100000")),
        positions=[make_position("AAPL", Decimal("200"))],
    )
    guard = RiskGuard(max_position_pct=Decimal("10"), max_daily_loss_pct=Decimal("5"))
    db_factory, _ = make_mock_db_session()
    manager = OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=make_mock_status_service("live"),
    )
    manager._pending["AAPL"] = Decimal("200")

    # process any signal to trigger reconciliation
    signal = make_signal_with_price(strength="1", reference_price=Decimal("50"))
    await manager.process_signal(signal)

    assert "AAPL" not in manager._pending


@pytest.mark.asyncio
async def test_pending_reconciliation_partial_fill():
    """If held (100) < pending (200), do NOT clear the pending entry."""
    adapter = make_mock_adapter(
        account=make_account_with_nav(Decimal("100000")),
        positions=[make_position("AAPL", Decimal("100"))],
    )
    guard = RiskGuard(max_position_pct=Decimal("10"), max_daily_loss_pct=Decimal("5"))
    db_factory, _ = make_mock_db_session()
    manager = OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=make_mock_status_service("live"),
    )
    manager._pending["AAPL"] = Decimal("200")

    signal = make_signal_with_price(strength="1", reference_price=Decimal("50"))
    await manager.process_signal(signal)

    # pending still present (partial fill only)
    assert "AAPL" in manager._pending
    assert manager._pending["AAPL"] == Decimal("200")


@pytest.mark.asyncio
async def test_pending_incremented_after_order():
    """After submitting a delta order, _pending[symbol] is incremented by delta."""
    adapter = make_mock_adapter(
        account=make_account_with_nav(Decimal("100000")),
        positions=[],
    )
    guard = RiskGuard(max_position_pct=Decimal("10"), max_daily_loss_pct=Decimal("5"))
    db_factory, _ = make_mock_db_session()
    manager = OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=make_mock_status_service("live"),
    )
    signal = make_signal_with_price(strength="1", reference_price=Decimal("50"))
    await manager.process_signal(signal)

    assert manager._pending.get("AAPL") == Decimal("200")
```

Also add `Position` to the imports at the top of the test file:
```python
from polara.broker.schemas import AccountInfo, OrderStatus, Position
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd /Users/cgncn/polara_quant/.claude/worktrees/pedantic-wilbur
uv run pytest tests/test_order_manager.py -k "delta or pending or reconcil" -v
```

Expected: FAILs (Position import may work but the delta/pending logic doesn't exist yet)

- [ ] **Step 3: Update `src/polara/order_manager/manager.py`**

Add `_pending` to `__init__` (after `self._min_order_quantity`):

```python
self._pending: dict[str, Decimal] = {}
```

Add `_reconcile_pending` and `_compute_delta` methods after `_compute_quantity`:

```python
def _reconcile_pending(self, positions: list) -> None:
    """Clear pending entries for symbols where held quantity >= pending quantity.

    Call this at the start of each process_signal cycle, after fetching live positions,
    to remove pending entries for orders that have been filled.
    """
    held_by_symbol = {p.symbol: p.quantity for p in positions}
    for symbol in list(self._pending):
        held = held_by_symbol.get(symbol, Decimal("0"))
        if held >= self._pending[symbol]:
            del self._pending[symbol]

def _compute_delta(
    self, symbol: str, quantity_target: Decimal, positions: list
) -> Decimal:
    """Compute the quantity still needed to reach target, accounting for in-flight orders.

    delta = max(0, target - held - in_flight)
    """
    held_by_symbol = {p.symbol: p.quantity for p in positions}
    current_held = held_by_symbol.get(symbol, Decimal("0"))
    in_flight = self._pending.get(symbol, Decimal("0"))
    return max(Decimal("0"), quantity_target - current_held - in_flight)
```

Update `process_signal` to call reconcile + delta. Replace the section from the risk checks through the `_compute_quantity` call:

```python
    try:
        account = await self._adapter.get_account()
        positions = await self._adapter.get_positions()
        self._reconcile_pending(positions)
        self._risk_guard.check_daily_loss(account)
        self._risk_guard.check_position_size(signal, positions, account)
    except RiskViolationError as e:
        logger.warning("Risk violation for signal %s: %s", signal.signal_id, e)
        return None

    quantity_target = self._compute_quantity(signal, account)
    if quantity_target is None:
        return None

    delta = self._compute_delta(signal.symbol, quantity_target, positions)
    if delta < self._min_order_quantity:
        logger.info(
            "Delta %s for %s is below minimum %s — skipping signal",
            delta, signal.symbol, self._min_order_quantity,
        )
        return None
```

Then replace the `quantity=quantity` in `OrderRequest` with `quantity=delta`:

```python
    side = "buy" if signal.strength > Decimal(0) else "sell"
    req = OrderRequest(
        order_id=uuid4(),
        symbol=signal.symbol,
        side=side,
        quantity=delta,
        limit_price=None,
        requested_at=datetime.now(UTC),
        strategy_id=signal.strategy_id,
    )
```

And after the `async with self._db() as db:` block completes, increment pending:

```python
    self._pending[signal.symbol] = (
        self._pending.get(signal.symbol, Decimal("0")) + delta
    )
    return order_status
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/cgncn/polara_quant/.claude/worktrees/pedantic-wilbur
uv run pytest tests/test_order_manager.py -v
```

Expected: all PASS

- [ ] **Step 5: Run ruff**

```bash
cd /Users/cgncn/polara_quant/.claude/worktrees/pedantic-wilbur
uv run ruff check src/
```

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
cd /Users/cgncn/polara_quant/.claude/worktrees/pedantic-wilbur
git add src/polara/order_manager/manager.py tests/test_order_manager.py
git commit -m "feat: delta-aware sizing and pending tracker in OrderManager"
```

---

## Task 5: OrderManager — _compute_exit_prices + bracket routing in process_signal

**Files:**
- Modify: `src/polara/order_manager/manager.py`
- Create: `tests/test_exit_prices.py`
- Modify: `tests/test_order_manager.py`

- [ ] **Step 1: Write 7 unit tests in new `tests/test_exit_prices.py`**

```python
"""Unit tests for OrderManager._compute_exit_prices."""
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from polara.order_manager.manager import OrderManager
from polara.risk_guard.guard import RiskGuard
from polara.schemas.signals import Signal


def make_manager() -> OrderManager:
    """Minimal OrderManager for testing _compute_exit_prices (no IB needed)."""
    adapter = MagicMock()
    guard = RiskGuard(max_position_pct=Decimal("10"), max_daily_loss_pct=Decimal("5"))
    db_factory = MagicMock()
    status_service = AsyncMock()
    return OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=status_service,
    )


def make_signal(
    stop_loss_pct: Decimal | None = None,
    take_profit_pct: Decimal | None = None,
    reference_price: Decimal | None = None,
) -> Signal:
    return Signal(
        signal_id=uuid4(),
        strategy_id="s1",
        symbol="AAPL",
        strength=Decimal("1"),
        generated_at=datetime.now(UTC),
        reference_price=reference_price,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
    )


def test_stop_price_buy_signal():
    """price=100, stop_loss_pct=5, buy → stop=95.00"""
    om = make_manager()
    sig = make_signal(stop_loss_pct=Decimal("5"), reference_price=Decimal("100"))
    stop, tp = om._compute_exit_prices(sig, "buy")
    assert stop == Decimal("95.00")
    assert tp is None


def test_take_profit_buy_signal():
    """price=100, take_profit_pct=10, buy → tp=110.00"""
    om = make_manager()
    sig = make_signal(take_profit_pct=Decimal("10"), reference_price=Decimal("100"))
    stop, tp = om._compute_exit_prices(sig, "buy")
    assert stop is None
    assert tp == Decimal("110.00")


def test_stop_price_sell_signal():
    """price=100, stop_loss_pct=5, sell → stop=105.00 (stop above for shorts)"""
    om = make_manager()
    sig = make_signal(stop_loss_pct=Decimal("5"), reference_price=Decimal("100"))
    stop, tp = om._compute_exit_prices(sig, "sell")
    assert stop == Decimal("105.00")


def test_take_profit_sell_signal():
    """price=100, take_profit_pct=10, sell → tp=90.00 (profit below for shorts)"""
    om = make_manager()
    sig = make_signal(take_profit_pct=Decimal("10"), reference_price=Decimal("100"))
    stop, tp = om._compute_exit_prices(sig, "sell")
    assert tp == Decimal("90.00")


def test_exit_prices_none_when_no_reference_price():
    """reference_price=None → (None, None) regardless of pct fields."""
    om = make_manager()
    sig = make_signal(
        stop_loss_pct=Decimal("5"),
        take_profit_pct=Decimal("10"),
        reference_price=None,
    )
    stop, tp = om._compute_exit_prices(sig, "buy")
    assert stop is None
    assert tp is None


def test_exit_prices_none_when_no_pct_set():
    """Both pcts None → (None, None)."""
    om = make_manager()
    sig = make_signal(reference_price=Decimal("100"))
    stop, tp = om._compute_exit_prices(sig, "buy")
    assert stop is None
    assert tp is None


def test_stop_price_rounded_to_cents():
    """price=100.005, stop_loss_pct=5 → result has exactly 2 decimal places."""
    om = make_manager()
    sig = make_signal(stop_loss_pct=Decimal("5"), reference_price=Decimal("100.005"))
    stop, _ = om._compute_exit_prices(sig, "buy")
    assert stop is not None
    # quantized to 0.01
    assert stop == stop.quantize(Decimal("0.01"))
```

- [ ] **Step 2: Write 4 failing tests in `tests/test_order_manager.py`**

Append to the test file:

```python
# ---------------------------------------------------------------------------
# Bracket routing tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bracket_order_submitted_when_stop_loss_set():
    """Signal with stop_loss_pct → place_bracket_order called, not place_order."""
    adapter = make_mock_adapter(account=make_account_with_nav(Decimal("100000")))
    adapter.place_bracket_order = AsyncMock(return_value=make_order_status())
    guard = RiskGuard(max_position_pct=Decimal("10"), max_daily_loss_pct=Decimal("5"))
    db_factory, _ = make_mock_db_session()
    manager = OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=make_mock_status_service("live"),
    )
    signal = Signal(
        signal_id=uuid4(),
        strategy_id="test-strategy",
        symbol="AAPL",
        strength=Decimal("1"),
        generated_at=datetime.now(UTC),
        reference_price=Decimal("50"),
        stop_loss_pct=Decimal("5"),
    )
    await manager.process_signal(signal)

    adapter.place_bracket_order.assert_called_once()
    adapter.place_order.assert_not_called()


@pytest.mark.asyncio
async def test_bracket_order_submitted_when_take_profit_set():
    """Signal with take_profit_pct → place_bracket_order called."""
    adapter = make_mock_adapter(account=make_account_with_nav(Decimal("100000")))
    adapter.place_bracket_order = AsyncMock(return_value=make_order_status())
    guard = RiskGuard(max_position_pct=Decimal("10"), max_daily_loss_pct=Decimal("5"))
    db_factory, _ = make_mock_db_session()
    manager = OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=make_mock_status_service("live"),
    )
    signal = Signal(
        signal_id=uuid4(),
        strategy_id="test-strategy",
        symbol="AAPL",
        strength=Decimal("1"),
        generated_at=datetime.now(UTC),
        reference_price=Decimal("50"),
        take_profit_pct=Decimal("10"),
    )
    await manager.process_signal(signal)

    adapter.place_bracket_order.assert_called_once()
    adapter.place_order.assert_not_called()


@pytest.mark.asyncio
async def test_plain_order_when_no_exit_params():
    """Signal with no stop/take-profit → plain place_order called (no regression)."""
    adapter = make_mock_adapter(account=make_account_with_nav(Decimal("100000")))
    guard = RiskGuard(max_position_pct=Decimal("10"), max_daily_loss_pct=Decimal("5"))
    db_factory, _ = make_mock_db_session()
    manager = OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=make_mock_status_service("live"),
    )
    signal = make_signal_with_price(strength="1", reference_price=Decimal("50"))
    await manager.process_signal(signal)

    adapter.place_order.assert_called_once()
    assert not hasattr(adapter, 'place_bracket_order') or \
        not adapter.place_bracket_order.called


@pytest.mark.asyncio
async def test_pending_incremented_after_bracket_order():
    """After bracket order, _pending[symbol] reflects the submitted delta."""
    adapter = make_mock_adapter(account=make_account_with_nav(Decimal("100000")))
    adapter.place_bracket_order = AsyncMock(return_value=make_order_status())
    guard = RiskGuard(max_position_pct=Decimal("10"), max_daily_loss_pct=Decimal("5"))
    db_factory, _ = make_mock_db_session()
    manager = OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=make_mock_status_service("live"),
    )
    signal = Signal(
        signal_id=uuid4(),
        strategy_id="test-strategy",
        symbol="AAPL",
        strength=Decimal("1"),
        generated_at=datetime.now(UTC),
        reference_price=Decimal("50"),
        stop_loss_pct=Decimal("5"),
    )
    await manager.process_signal(signal)

    assert manager._pending.get("AAPL") == Decimal("200")
```

- [ ] **Step 3: Run to confirm new tests fail**

```bash
cd /Users/cgncn/polara_quant/.claude/worktrees/pedantic-wilbur
uv run pytest tests/test_exit_prices.py tests/test_order_manager.py -k "exit_price or bracket" -v
```

Expected: FAILs

- [ ] **Step 4: Add `ROUND_UP` import and `_compute_exit_prices` to `src/polara/order_manager/manager.py`**

Update the decimal import line (currently `from decimal import ROUND_DOWN, Decimal`) to:

```python
from decimal import ROUND_DOWN, ROUND_UP, Decimal
```

Add `_compute_exit_prices` method after `_compute_delta`:

```python
def _compute_exit_prices(
    self, signal: Signal, side: str
) -> tuple[Decimal | None, Decimal | None]:
    """Convert percentage stop/take-profit params to absolute prices.

    For buys:  stop  = price × (1 - pct/100), rounded down to nearest cent
               tp    = price × (1 + pct/100), rounded up to nearest cent
    For sells: stop  = price × (1 + pct/100), rounded up   (stop above entry)
               tp    = price × (1 - pct/100), rounded down (profit below entry)

    Returns (None, None) if reference_price is not set on the signal.
    """
    if signal.reference_price is None:
        return None, None

    price = signal.reference_price
    stop: Decimal | None = None
    take_profit: Decimal | None = None

    if side == "buy":
        if signal.stop_loss_pct:
            stop = (price * (1 - signal.stop_loss_pct / Decimal("100"))).quantize(
                Decimal("0.01"), rounding=ROUND_DOWN
            )
        if signal.take_profit_pct:
            take_profit = (
                price * (1 + signal.take_profit_pct / Decimal("100"))
            ).quantize(Decimal("0.01"), rounding=ROUND_UP)
    else:  # sell / short
        if signal.stop_loss_pct:
            stop = (price * (1 + signal.stop_loss_pct / Decimal("100"))).quantize(
                Decimal("0.01"), rounding=ROUND_UP
            )
        if signal.take_profit_pct:
            take_profit = (
                price * (1 - signal.take_profit_pct / Decimal("100"))
            ).quantize(Decimal("0.01"), rounding=ROUND_DOWN)

    return stop, take_profit
```

- [ ] **Step 5: Update `process_signal` to call `_compute_exit_prices` and route to bracket vs plain**

Update `_INSERT_SIGNAL_ORDER` at the top of the file to include the new columns:

```python
_INSERT_SIGNAL_ORDER = text(
    "INSERT INTO signal_orders"
    " (id, signal_id, order_id, strategy_id, symbol, signal_strength,"
    "  stop_price, take_profit_price, created_at)"
    " VALUES (:id, :signal_id, :order_id, :strategy_id, :symbol, :signal_strength,"
    "  :stop_price, :take_profit_price, :created_at)"
)
```

In `process_signal`, after computing `delta` and before constructing `OrderRequest`, add:

```python
    stop_price, take_profit_price = self._compute_exit_prices(signal, side)
```

Wait — `side` is declared after `delta`. Reorder: compute `side` first, then call `_compute_exit_prices`:

```python
    side = "buy" if signal.strength > Decimal(0) else "sell"
    stop_price, take_profit_price = self._compute_exit_prices(signal, side)

    req = OrderRequest(
        order_id=uuid4(),
        symbol=signal.symbol,
        side=side,
        quantity=delta,
        limit_price=None,
        requested_at=datetime.now(UTC),
        strategy_id=signal.strategy_id,
    )

    async with self._db() as db:
        if stop_price is not None or take_profit_price is not None:
            order_status = await self._adapter.place_bracket_order(
                req, stop_price, take_profit_price, db
            )
        else:
            order_status = await self._adapter.place_order(req, db)
        await db.execute(
            _INSERT_SIGNAL_ORDER,
            {
                "id": str(uuid4()),
                "signal_id": str(signal.signal_id),
                "order_id": str(req.order_id),
                "strategy_id": signal.strategy_id,
                "symbol": signal.symbol,
                "signal_strength": str(signal.strength),
                "stop_price": str(stop_price) if stop_price is not None else None,
                "take_profit_price": (
                    str(take_profit_price) if take_profit_price is not None else None
                ),
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
        await db.commit()

    self._pending[signal.symbol] = (
        self._pending.get(signal.symbol, Decimal("0")) + delta
    )
    return order_status
```

- [ ] **Step 6: Run all tests**

```bash
cd /Users/cgncn/polara_quant/.claude/worktrees/pedantic-wilbur
uv run pytest
```

Expected: all PASS

- [ ] **Step 7: Ruff**

```bash
cd /Users/cgncn/polara_quant/.claude/worktrees/pedantic-wilbur
uv run ruff check src/
```

Expected: `All checks passed!`

- [ ] **Step 8: Commit**

```bash
cd /Users/cgncn/polara_quant/.claude/worktrees/pedantic-wilbur
git add src/polara/order_manager/manager.py tests/test_exit_prices.py tests/test_order_manager.py
git commit -m "feat: exit price computation and bracket order routing in OrderManager"
```

---

## Task 6: Strategy updates — optional stop/take-profit env var fields

**Files:**
- Modify: `src/polara/research_engine/strategies/ma_crossover.py`
- Modify: `src/polara/research_engine/strategies/rsi_mean_reversion.py`
- Modify: `src/polara/api/main.py`

No new tests needed — existing strategy tests pass `None` fields (the fields default to `None`), and the wiring in `main.py` mirrors the existing env var pattern.

- [ ] **Step 1: Add optional fields to `MACrossoverStrategy`**

In `src/polara/research_engine/strategies/ma_crossover.py`, the dataclass currently has:
```python
quantity: Decimal
bar_size: str
```

Add after `bar_size`:
```python
stop_loss_pct: Decimal | None = None
take_profit_pct: Decimal | None = None
```

Update the `Signal(...)` construction in `on_bars` to pass these fields:

```python
        return Signal(
            signal_id=uuid4(),
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            strength=strength,
            generated_at=datetime.now(UTC),
            reference_price=bars[-1].close,
            stop_loss_pct=self.stop_loss_pct,
            take_profit_pct=self.take_profit_pct,
        )
```

- [ ] **Step 2: Add optional fields to `RSIMeanReversionStrategy`**

Same change in `src/polara/research_engine/strategies/rsi_mean_reversion.py`. The dataclass currently ends at `bar_size: str`. Add:

```python
stop_loss_pct: Decimal | None = None
take_profit_pct: Decimal | None = None
```

Update the `Signal(...)` construction in `on_bars`:

```python
        return Signal(
            signal_id=uuid4(),
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            strength=strength,
            generated_at=datetime.now(UTC),
            reference_price=bars[-1].close,
            stop_loss_pct=self.stop_loss_pct,
            take_profit_pct=self.take_profit_pct,
        )
```

- [ ] **Step 3: Wire env vars in `src/polara/api/main.py`**

Find where `MACrossoverStrategy(...)` and `RSIMeanReversionStrategy(...)` are constructed in the lifespan. Each strategy already reads env vars for params. Add:

For `MACrossoverStrategy`:
```python
stop_loss_pct=Decimal(os.environ["MA_STOP_LOSS_PCT"]) if os.environ.get("MA_STOP_LOSS_PCT") else None,
take_profit_pct=Decimal(os.environ["MA_TAKE_PROFIT_PCT"]) if os.environ.get("MA_TAKE_PROFIT_PCT") else None,
```

For `RSIMeanReversionStrategy`:
```python
stop_loss_pct=Decimal(os.environ["RSI_STOP_LOSS_PCT"]) if os.environ.get("RSI_STOP_LOSS_PCT") else None,
take_profit_pct=Decimal(os.environ["RSI_TAKE_PROFIT_PCT"]) if os.environ.get("RSI_TAKE_PROFIT_PCT") else None,
```

- [ ] **Step 4: Run full suite**

```bash
cd /Users/cgncn/polara_quant/.claude/worktrees/pedantic-wilbur
uv run pytest
```

Expected: all PASS

- [ ] **Step 5: Ruff**

```bash
cd /Users/cgncn/polara_quant/.claude/worktrees/pedantic-wilbur
uv run ruff check src/
```

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
cd /Users/cgncn/polara_quant/.claude/worktrees/pedantic-wilbur
git add src/polara/research_engine/strategies/ma_crossover.py \
        src/polara/research_engine/strategies/rsi_mean_reversion.py \
        src/polara/api/main.py
git commit -m "feat: optional stop_loss_pct and take_profit_pct on strategies"
```

---

## Task 7: Final verification

**Files:** None (verification only)

- [ ] **Step 1: Run complete test suite**

```bash
cd /Users/cgncn/polara_quant/.claude/worktrees/pedantic-wilbur
uv run pytest -v
```

Expected: all tests PASS (219+ tests)

- [ ] **Step 2: Ruff on all source**

```bash
cd /Users/cgncn/polara_quant/.claude/worktrees/pedantic-wilbur
uv run ruff check src/
```

Expected: `All checks passed!`

- [ ] **Step 3: Apply migration to verify it runs clean**

```bash
cd /Users/cgncn/polara_quant/.claude/worktrees/pedantic-wilbur
uv run alembic upgrade head
```

Expected: no errors

- [ ] **Step 4: Verify math (manual spot-check)**

Confirm the following calculations are correct in the test output:
- Buy: price=100, stop_loss_pct=5 → stop=95.00 (`100 × (1 − 0.05) = 95.00`) ✓
- Buy: price=100, take_profit_pct=10 → tp=110.00 (`100 × 1.10 = 110.00`) ✓
- Sell: price=100, stop_loss_pct=5 → stop=105.00 (`100 × 1.05 = 105.00`) ✓
- Sell: price=100, take_profit_pct=10 → tp=90.00 (`100 × 0.90 = 90.00`) ✓

- [ ] **Step 5: Update memory**

The phase status memory at `/Users/cgncn/.claude/projects/-Users-cgncn-polara-quant/memory/project_phase_status.md` should be updated to record Phase 6 complete.
