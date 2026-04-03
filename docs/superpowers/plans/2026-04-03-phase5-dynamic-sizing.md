# Phase 5: Dynamic Order Sizing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded `quantity=Decimal("1")` in `OrderManager` with a formula that scales order size proportionally to signal strength and account NAV: `floor(NAV × max_position_pct% × |strength| / reference_price)`.

**Architecture:** `Signal` gains an optional `reference_price` field set by each strategy from `bars[-1].close`. `RiskGuard` exposes `max_position_pct` as a property. `OrderManager` reads both to compute dynamic quantity, with a configurable minimum-quantity guard that skips the order if the result is too small.

**Tech Stack:** Python 3.12+, Pydantic v2, `decimal.ROUND_DOWN`, SQLAlchemy async, FastAPI, pytest-asyncio, uv

---

## File Map

| Action | File | Change |
|---|---|---|
| Modify | `src/polara/schemas/signals.py` | Add `reference_price: Decimal \| None = None` with float-reject validator |
| Modify | `src/polara/risk_guard/guard.py` | Add `max_position_pct` property returning pct as Decimal |
| Modify | `src/polara/order_manager/manager.py` | Dynamic sizing formula + `min_order_quantity` param |
| Modify | `src/polara/research_engine/strategies/ma_crossover.py` | Set `reference_price=bars[-1].close` on emitted Signal |
| Modify | `src/polara/research_engine/strategies/rsi_mean_reversion.py` | Same |
| Modify | `src/polara/api/main.py` | Pass `min_order_quantity` to `OrderManager` |
| Modify | `tests/test_schemas.py` | Add `reference_price` test; existing tests unaffected (field is optional) |
| Modify | `tests/test_risk_guard.py` | Add `max_position_pct` property test |
| Modify | `tests/test_order_manager.py` | Add 7 new dynamic sizing tests; update `make_signal` helper |
| Modify | `tests/test_research_engine.py` | Assert `signal.reference_price == bars[-1].close` |
| Modify | `tests/test_rsi_strategy.py` | Assert `signal.reference_price == bars[-1].close` |

---

## Task 1: Add `reference_price` to Signal schema

**Files:**
- Modify: `src/polara/schemas/signals.py`
- Test: `tests/test_schemas.py`

- [ ] **Step 1: Write the failing test**

Open `tests/test_schemas.py` and add at the end of the Signal section:

```python
def test_signal_reference_price_defaults_to_none():
    s = Signal(
        signal_id=uuid4(),
        strategy_id="s1",
        symbol="AAPL",
        strength=Decimal("1"),
        generated_at=datetime.now(UTC),
    )
    assert s.reference_price is None


def test_signal_reference_price_accepts_decimal():
    s = Signal(
        signal_id=uuid4(),
        strategy_id="s1",
        symbol="AAPL",
        strength=Decimal("1"),
        generated_at=datetime.now(UTC),
        reference_price=Decimal("150.00"),
    )
    assert s.reference_price == Decimal("150.00")


def test_signal_reference_price_rejects_float():
    with pytest.raises(Exception):
        Signal(
            signal_id=uuid4(),
            strategy_id="s1",
            symbol="AAPL",
            strength=Decimal("1"),
            generated_at=datetime.now(UTC),
            reference_price=150.0,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_schemas.py::test_signal_reference_price_defaults_to_none tests/test_schemas.py::test_signal_reference_price_accepts_decimal tests/test_schemas.py::test_signal_reference_price_rejects_float -v
```

Expected: FAIL — `Signal` has no `reference_price` field.

- [ ] **Step 3: Add the field to Signal**

In `src/polara/schemas/signals.py`, add `reference_price` after `strength` and before the validators:

```python
class Signal(BaseModel):
    model_config = ConfigDict(strict=True)

    signal_id: UUID
    strategy_id: str
    symbol: str
    strength: Decimal
    generated_at: datetime
    reference_price: Decimal | None = None

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

    @field_validator("reference_price", mode="before")
    @classmethod
    def reject_float_price(cls, v: object) -> object:
        if isinstance(v, float):
            raise ValueError("float is not allowed for reference_price; use Decimal")
        return v
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_schemas.py -v
```

Expected: all PASS (existing Signal tests still pass because `reference_price` is optional).

- [ ] **Step 5: Commit**

```bash
git add src/polara/schemas/signals.py tests/test_schemas.py
git commit -m "feat: add optional reference_price field to Signal"
```

---

## Task 2: Expose `max_position_pct` property on RiskGuard

**Files:**
- Modify: `src/polara/risk_guard/guard.py`
- Test: `tests/test_risk_guard.py`

- [ ] **Step 1: Write the failing test**

Add at the end of `tests/test_risk_guard.py`:

```python
def test_max_position_pct_property_returns_percentage():
    guard = RiskGuard(max_position_pct=Decimal("10"), max_daily_loss_pct=Decimal("5"))
    assert guard.max_position_pct == Decimal("10")


def test_max_position_pct_property_reflects_constructor_value():
    guard = RiskGuard(max_position_pct=Decimal("25"), max_daily_loss_pct=Decimal("5"))
    assert guard.max_position_pct == Decimal("25")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_risk_guard.py::test_max_position_pct_property_returns_percentage tests/test_risk_guard.py::test_max_position_pct_property_reflects_constructor_value -v
```

Expected: FAIL — `RiskGuard` has no `max_position_pct` attribute.

- [ ] **Step 3: Add the property**

In `src/polara/risk_guard/guard.py`, add after `__init__`:

```python
    @property
    def max_position_pct(self) -> Decimal:
        """Return the maximum position size as a percentage (e.g. 10 for 10%)."""
        return self._max_position * Decimal(100)
```

The full `__init__` + property block should now look like:

```python
    def __init__(self, max_position_pct: Decimal, max_daily_loss_pct: Decimal) -> None:
        # Store as fractions (e.g. 10 -> 0.10)
        self._max_position = max_position_pct / Decimal(100)
        self._max_daily_loss = max_daily_loss_pct / Decimal(100)
        self._halted: bool = False
        self._halt_date: date | None = None

    @property
    def max_position_pct(self) -> Decimal:
        """Return the maximum position size as a percentage (e.g. 10 for 10%)."""
        return self._max_position * Decimal(100)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_risk_guard.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/polara/risk_guard/guard.py tests/test_risk_guard.py
git commit -m "feat: expose max_position_pct property on RiskGuard"
```

---

## Task 3: Dynamic sizing in OrderManager

**Files:**
- Modify: `src/polara/order_manager/manager.py`
- Test: `tests/test_order_manager.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_order_manager.py`. First update `make_signal` to optionally accept `reference_price`:

```python
def make_signal(symbol: str = "AAPL", strength: str = "1", reference_price: str | None = "50") -> Signal:
    return Signal(
        signal_id=uuid4(),
        strategy_id="test-strategy",
        symbol=symbol,
        strength=Decimal(strength),
        generated_at=datetime.now(UTC),
        reference_price=Decimal(reference_price) if reference_price is not None else None,
    )
```

Then add these tests at the end of the file:

```python
def make_manager_with_pct(pct: str = "10", min_qty: str = "1") -> OrderManager:
    adapter = make_mock_adapter()
    guard = RiskGuard(max_position_pct=Decimal(pct), max_daily_loss_pct=Decimal("5"))
    db_factory, _ = make_mock_db_session()
    return OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=make_mock_status_service("live"),
        min_order_quantity=Decimal(min_qty),
    ), adapter


@pytest.mark.asyncio
async def test_dynamic_sizing_full_strength():
    """strength=1.0, NAV=100000, pct=10%, price=50 → quantity=200"""
    manager, adapter = make_manager_with_pct(pct="10")
    adapter.get_account = AsyncMock(return_value=AccountInfo(
        net_liquidation=Decimal("100000"),
        cash=Decimal("50000"),
        unrealised_pnl=Decimal("0"),
        realised_pnl=Decimal("0"),
        currency="USD",
        timestamp=datetime.now(UTC),
    ))
    signal = make_signal(strength="1", reference_price="50")
    await manager.process_signal(signal)
    order_req = adapter.place_order.call_args[0][0]
    assert order_req.quantity == Decimal("200")


@pytest.mark.asyncio
async def test_dynamic_sizing_half_strength():
    """strength=0.5, NAV=100000, pct=10%, price=50 → quantity=100"""
    manager, adapter = make_manager_with_pct(pct="10")
    adapter.get_account = AsyncMock(return_value=AccountInfo(
        net_liquidation=Decimal("100000"),
        cash=Decimal("50000"),
        unrealised_pnl=Decimal("0"),
        realised_pnl=Decimal("0"),
        currency="USD",
        timestamp=datetime.now(UTC),
    ))
    signal = make_signal(strength="0.5", reference_price="50")
    await manager.process_signal(signal)
    order_req = adapter.place_order.call_args[0][0]
    assert order_req.quantity == Decimal("100")


@pytest.mark.asyncio
async def test_dynamic_sizing_uses_floor_not_round():
    """NAV=100000, pct=10%, strength=1, price=33 → 100000*0.10/33=303.03 → floor=303"""
    manager, adapter = make_manager_with_pct(pct="10")
    adapter.get_account = AsyncMock(return_value=AccountInfo(
        net_liquidation=Decimal("100000"),
        cash=Decimal("50000"),
        unrealised_pnl=Decimal("0"),
        realised_pnl=Decimal("0"),
        currency="USD",
        timestamp=datetime.now(UTC),
    ))
    signal = make_signal(strength="1", reference_price="33")
    await manager.process_signal(signal)
    order_req = adapter.place_order.call_args[0][0]
    assert order_req.quantity == Decimal("303")


@pytest.mark.asyncio
async def test_dynamic_sizing_quantity_is_decimal():
    manager, adapter = make_manager_with_pct()
    signal = make_signal(reference_price="50")
    await manager.process_signal(signal)
    order_req = adapter.place_order.call_args[0][0]
    assert isinstance(order_req.quantity, Decimal)


@pytest.mark.asyncio
async def test_dynamic_sizing_no_reference_price_falls_back_to_one():
    """reference_price=None → falls back to quantity=1"""
    manager, adapter = make_manager_with_pct()
    signal = make_signal(reference_price=None)
    await manager.process_signal(signal)
    order_req = adapter.place_order.call_args[0][0]
    assert order_req.quantity == Decimal("1")


@pytest.mark.asyncio
async def test_dynamic_sizing_below_minimum_returns_none():
    """NAV=100, pct=10%, strength=1, price=50 → qty=0 < min=1 → skip"""
    manager, adapter = make_manager_with_pct(pct="10", min_qty="1")
    adapter.get_account = AsyncMock(return_value=AccountInfo(
        net_liquidation=Decimal("100"),
        cash=Decimal("50"),
        unrealised_pnl=Decimal("0"),
        realised_pnl=Decimal("0"),
        currency="USD",
        timestamp=datetime.now(UTC),
    ))
    signal = make_signal(strength="1", reference_price="50")
    result = await manager.process_signal(signal)
    assert result is None
    adapter.place_order.assert_not_called()


@pytest.mark.asyncio
async def test_dynamic_sizing_custom_minimum_skips_small_orders():
    """qty=100 but min=200 → skip"""
    manager, adapter = make_manager_with_pct(pct="10", min_qty="200")
    adapter.get_account = AsyncMock(return_value=AccountInfo(
        net_liquidation=Decimal("100000"),
        cash=Decimal("50000"),
        unrealised_pnl=Decimal("0"),
        realised_pnl=Decimal("0"),
        currency="USD",
        timestamp=datetime.now(UTC),
    ))
    signal = make_signal(strength="0.5", reference_price="50")  # qty=100
    result = await manager.process_signal(signal)
    assert result is None
    adapter.place_order.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_order_manager.py::test_dynamic_sizing_full_strength tests/test_order_manager.py::test_dynamic_sizing_half_strength tests/test_order_manager.py::test_dynamic_sizing_below_minimum_returns_none -v
```

Expected: FAIL — `OrderManager.__init__` has no `min_order_quantity` param and quantity is still hardcoded.

- [ ] **Step 3: Implement dynamic sizing in OrderManager**

Replace the full content of `src/polara/order_manager/manager.py`:

```python
"""OrderManager — links signals to order submissions via RiskGuard + BrokerAdapter."""
import logging
from datetime import UTC, datetime
from decimal import Decimal, ROUND_DOWN
from uuid import uuid4

from sqlalchemy import text

from polara.broker.adapter import BrokerAdapter
from polara.broker.schemas import OrderStatus
from polara.research_engine.status_service import StrategyStatusService
from polara.risk_guard.exceptions import RiskViolationError
from polara.risk_guard.guard import RiskGuard
from polara.schemas.orders import OrderRequest
from polara.schemas.signals import Signal

logger = logging.getLogger(__name__)

_INSERT_SIGNAL_ORDER = text(
    "INSERT INTO signal_orders"
    " (id, signal_id, order_id, strategy_id, symbol, signal_strength, created_at)"
    " VALUES (:id, :signal_id, :order_id, :strategy_id, :symbol, :signal_strength, :created_at)"
)


class OrderManager:
    """Processes signals: runs risk checks then submits orders via BrokerAdapter."""

    def __init__(
        self,
        broker_adapter: BrokerAdapter,
        risk_guard: RiskGuard,
        db_session_factory,
        status_service: StrategyStatusService,
        min_order_quantity: Decimal = Decimal("1"),
    ) -> None:
        self._adapter = broker_adapter
        self._risk_guard = risk_guard
        self._db = db_session_factory
        self._status_service = status_service
        self._min_order_quantity = min_order_quantity

    def _compute_quantity(self, signal: Signal, nav: Decimal) -> Decimal:
        """Compute order quantity from signal strength and account NAV.

        Formula: floor(NAV × (max_position_pct / 100) × |strength| / reference_price)
        Falls back to quantity=1 (with warning) if reference_price is None.
        """
        if signal.reference_price and signal.reference_price > Decimal(0):
            target_notional = (
                nav
                * (self._risk_guard.max_position_pct / Decimal("100"))
                * abs(signal.strength)
            )
            return (target_notional / signal.reference_price).to_integral_value(
                rounding=ROUND_DOWN
            )
        logger.warning(
            "Signal for %s has no reference_price — falling back to quantity=1",
            signal.symbol,
        )
        return Decimal("1")

    async def process_signal(self, signal: Signal) -> OrderStatus | None:
        """Run risk checks and submit order.

        Returns None if strategy is not live, risk check fails, or
        computed quantity is below min_order_quantity.
        """
        status = await self._status_service.get_status(signal.strategy_id)
        if status != "live":
            logger.info(
                "Signal from strategy %s skipped — status is %r (not live)",
                signal.strategy_id,
                status,
            )
            return None

        try:
            account = await self._adapter.get_account()
            positions = await self._adapter.get_positions()
            self._risk_guard.check_daily_loss(account)
            self._risk_guard.check_position_size(signal, positions, account)
        except RiskViolationError as e:
            logger.warning("Risk violation for signal %s: %s", signal.signal_id, e)
            return None

        quantity = self._compute_quantity(signal, account.net_liquidation)
        if quantity < self._min_order_quantity:
            logger.info(
                "Computed quantity %s for %s is below minimum %s — skipping signal",
                quantity,
                signal.symbol,
                self._min_order_quantity,
            )
            return None

        side = "buy" if signal.strength > Decimal(0) else "sell"
        req = OrderRequest(
            order_id=uuid4(),
            symbol=signal.symbol,
            side=side,
            quantity=quantity,
            limit_price=None,
            requested_at=datetime.now(UTC),
            strategy_id=signal.strategy_id,
        )

        async with self._db() as db:
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
                    "created_at": datetime.now(UTC).isoformat(),
                },
            )
            await db.commit()

        return order_status
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_order_manager.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/polara/order_manager/manager.py tests/test_order_manager.py
git commit -m "feat: dynamic order sizing from signal strength and account NAV"
```

---

## Task 4: Set `reference_price` in both strategies

**Files:**
- Modify: `src/polara/research_engine/strategies/ma_crossover.py`
- Modify: `src/polara/research_engine/strategies/rsi_mean_reversion.py`
- Test: `tests/test_research_engine.py`
- Test: `tests/test_rsi_strategy.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_research_engine.py`, find the test that asserts on the returned signal from `MACrossoverStrategy.on_bars()`. Add one assertion to it:

```python
# Locate the existing test that calls on_bars and gets a Signal back.
# Add to it (do not create a duplicate test):
assert signal.reference_price == bars[-1].close
```

If the existing test is named something like `test_ma_crossover_buy_signal`, add the assertion there. If no such assertion exists yet, add a new test:

```python
def test_ma_crossover_signal_sets_reference_price():
    strategy = MACrossoverStrategy(
        strategy_id="test",
        symbol="AAPL",
        fast_period=2,
        slow_period=3,
        quantity=Decimal("1"),
        bar_size="5 mins",
    )
    # Construct bars that produce a crossover: fast crosses above slow on last bar.
    # slow_period+1 = 4 bars needed.
    closes = [Decimal("10"), Decimal("10"), Decimal("10"), Decimal("20")]
    bars = [
        Bar(
            symbol="AAPL",
            timestamp=datetime(2026, 1, i + 1, 10, 0, tzinfo=UTC),
            open=c, high=c + Decimal("1"), low=c - Decimal("1"), close=c, volume=100,
        )
        for i, c in enumerate(closes)
    ]
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.reference_price == Decimal("20")
```

In `tests/test_rsi_strategy.py`, add to `test_buy_signal_when_oversold` (or add a new test):

```python
def test_rsi_signal_sets_reference_price():
    strategy = make_strategy()
    # 20 bars all decreasing to push RSI < 30
    bars = [make_bar(close=Decimal(str(100 - i * 3)), i=i) for i in range(20)]
    signal = strategy.on_bars(bars)
    if signal is not None:
        assert signal.reference_price == bars[-1].close
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_research_engine.py tests/test_rsi_strategy.py -k "reference_price" -v
```

Expected: FAIL — strategies don't set `reference_price`.

- [ ] **Step 3: Update MACrossoverStrategy**

In `src/polara/research_engine/strategies/ma_crossover.py`, change the `return Signal(...)` call at line 61:

```python
        return Signal(
            signal_id=uuid4(),
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            strength=strength,
            generated_at=datetime.now(UTC),
            reference_price=bars[-1].close,
        )
```

- [ ] **Step 4: Update RSIMeanReversionStrategy**

In `src/polara/research_engine/strategies/rsi_mean_reversion.py`, change the `return Signal(...)` call at line 77:

```python
        return Signal(
            signal_id=uuid4(),
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            strength=strength,
            generated_at=datetime.now(UTC),
            reference_price=bars[-1].close,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_research_engine.py tests/test_rsi_strategy.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/polara/research_engine/strategies/ma_crossover.py \
        src/polara/research_engine/strategies/rsi_mean_reversion.py \
        tests/test_research_engine.py \
        tests/test_rsi_strategy.py
git commit -m "feat: strategies set reference_price on emitted signals"
```

---

## Task 5: Wire `min_order_quantity` in main.py

**Files:**
- Modify: `src/polara/api/main.py`

- [ ] **Step 1: Update OrderManager construction in lifespan**

In `src/polara/api/main.py`, find the `OrderManager(...)` instantiation (currently around line 69) and add `min_order_quantity`:

```python
        order_manager = OrderManager(
            broker_adapter=adapter,
            risk_guard=risk_guard,
            db_session_factory=AsyncSessionLocal,
            status_service=status_service,
            min_order_quantity=Decimal(os.environ.get("MIN_ORDER_QUANTITY", "1")),
        )
```

- [ ] **Step 2: Run the full suite**

```bash
uv run pytest
```

Expected: all 208+ tests PASS.

- [ ] **Step 3: Lint check**

```bash
uv run ruff check src/
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add src/polara/api/main.py
git commit -m "feat: wire MIN_ORDER_QUANTITY env var into OrderManager"
```

---

## Task 6: Final verification

- [ ] **Step 1: Run full test suite**

```bash
uv run pytest -v
```

Expected: all tests PASS. Count should be ≥ 215 (208 prior + 7 new sizing tests + 2 risk guard + 3 schema + 2 strategy reference_price tests).

- [ ] **Step 2: Lint**

```bash
uv run ruff check src/
```

Expected: no errors.

- [ ] **Step 3: Confirm the sizing math manually**

Check this calculation in a Python REPL:

```python
from decimal import Decimal, ROUND_DOWN
nav = Decimal("100000")
pct = Decimal("10")
strength = Decimal("1")
price = Decimal("50")
target = nav * (pct / Decimal("100")) * strength
qty = (target / price).to_integral_value(rounding=ROUND_DOWN)
assert qty == Decimal("200")

# Floor check
price2 = Decimal("33")
qty2 = (nav * (pct / Decimal("100")) / price2).to_integral_value(rounding=ROUND_DOWN)
assert qty2 == Decimal("303")  # not 304
```

- [ ] **Step 4: Push**

```bash
git push
```
