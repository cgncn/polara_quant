# Phase 6: Bracket Orders, Stop-Loss / Take-Profit, and Delta-Aware Sizing

## Context

After Phase 5, every order placed by `OrderManager` is a plain market order with no exit mechanism. A position stays open indefinitely until manually cancelled via the API. Additionally, `OrderManager` does not account for in-flight orders when computing quantity — if a signal fires while a prior order for the same symbol is still pending (submitted but not yet reflected in position data), it will submit a full-sized second order and overshoot `max_position_pct`.

Phase 6 fixes both gaps in a single coherent change:

1. **Bracket orders** — strategies can specify percentage-based stop-loss and take-profit levels on a `Signal`. `OrderManager` converts these to absolute prices and submits an IB bracket order (parent + stop child + take-profit child). IB manages exit execution autonomously, even if the app disconnects.

2. **Delta-aware sizing** — `OrderManager` maintains an in-memory `_pending` tracker (symbol → quantity in-flight). Before computing order size, it subtracts pending quantity from the target, ordering only the delta. Pending entries are reconciled against live position data on each scheduler cycle.

---

## Architecture

Three connected changes with no new services:

```
Signal(stop_loss_pct=5, take_profit_pct=10)
    → OrderManager._compute_quantity()        # Phase 5 target qty
    → OrderManager._compute_delta()           # subtract held + pending
    → delta < min_order_quantity → skip
    → _compute_exit_prices()                  # % → absolute prices
    → adapter.place_bracket_order()           # or place_order() if no exit params
    → self._pending[symbol] += delta
    ← next cycle: reconcile _pending vs live positions
```

---

## Changes

### 1. `Signal` schema — add exit params

**File:** `src/polara/schemas/signals.py`

```python
stop_loss_pct: Decimal | None = None
take_profit_pct: Decimal | None = None
```

Both optional (existing callers unaffected). Float-reject validators using the same `mode="before"` pattern as `reference_price`. If both are `None`, `OrderManager` submits a plain market order — no behaviour change for existing strategies.

Validation rules:
- `stop_loss_pct` must be > 0 and < 100 if set
- `take_profit_pct` must be > 0 if set
- Both are percentages (e.g. `Decimal("5")` = 5%)

### 2. `BrokerAdapter` — add `place_bracket_order`

**File:** `src/polara/broker/adapter.py`

New method:

```python
async def place_bracket_order(
    self,
    req: OrderRequest,
    stop_price: Decimal,
    take_profit_price: Decimal,
    db,
) -> OrderStatus:
```

Submits three linked IB orders:
- **Parent:** `MarketOrder(action, quantity, transmit=False)`
- **Stop child:** `StopOrder(opposite_action, quantity, float(stop_price), parentId=parent_id, transmit=False)`
- **Take-profit child:** `LimitOrder(opposite_action, quantity, float(take_profit_price), parentId=parent_id, transmit=True)`

IB requires `transmit=False` on parent and all children except the last; the final `transmit=True` atomically submits the entire bracket. `opposite_action` = "SELL" for buy brackets, "BUY" for sell brackets.

All three IB order IDs are stored. The `orders` table records the parent order; stop and take-profit child IDs are recorded in a new `bracket_orders` table (see Migration below).

### 3. `OrderManager` — delta sizing + bracket routing

**File:** `src/polara/order_manager/manager.py`

#### Constructor change

```python
def __init__(self, ...) -> None:
    ...
    self._pending: dict[str, Decimal] = {}
```

No new constructor parameter — `_pending` is internal state.

#### New private methods

**`_reconcile_pending(positions)`** — called at the top of `process_signal` after fetching live positions:

```python
def _reconcile_pending(self, positions: list[Position]) -> None:
    held_by_symbol = {p.symbol: p.quantity for p in positions}
    for symbol in list(self._pending):
        held = held_by_symbol.get(symbol, Decimal("0"))
        if held >= self._pending[symbol]:
            del self._pending[symbol]
```

**`_compute_delta(symbol, quantity_target, positions)`**:

```python
def _compute_delta(
    self,
    symbol: str,
    quantity_target: Decimal,
    positions: list[Position],
) -> Decimal:
    held_by_symbol = {p.symbol: p.quantity for p in positions}
    current_held = held_by_symbol.get(symbol, Decimal("0"))
    in_flight = self._pending.get(symbol, Decimal("0"))
    return max(Decimal("0"), quantity_target - current_held - in_flight)
```

**`_compute_exit_prices(signal, side)`** — converts percentage params to absolute prices:

```python
def _compute_exit_prices(
    self, signal: Signal, side: str
) -> tuple[Decimal | None, Decimal | None]:
    if signal.reference_price is None:
        return None, None
    price = signal.reference_price
    if side == "buy":
        stop = (price * (1 - signal.stop_loss_pct / 100)).quantize(
            Decimal("0.01"), rounding=ROUND_DOWN
        ) if signal.stop_loss_pct else None
        take_profit = (price * (1 + signal.take_profit_pct / 100)).quantize(
            Decimal("0.01"), rounding=ROUND_UP
        ) if signal.take_profit_pct else None
    else:  # sell / short
        stop = (price * (1 + signal.stop_loss_pct / 100)).quantize(
            Decimal("0.01"), rounding=ROUND_UP
        ) if signal.stop_loss_pct else None
        take_profit = (price * (1 - signal.take_profit_pct / 100)).quantize(
            Decimal("0.01"), rounding=ROUND_DOWN
        ) if signal.take_profit_pct else None
    return stop, take_profit
```

#### Updated `process_signal` flow

```python
account = await self._adapter.get_account()
positions = await self._adapter.get_positions()

# reconcile before risk checks
self._reconcile_pending(positions)

self._risk_guard.check_daily_loss(account)
self._risk_guard.check_position_size(signal, positions, account)

quantity_target = self._compute_quantity(signal, account)
if quantity_target is None:
    return None

delta = self._compute_delta(signal.symbol, quantity_target, positions)
if delta < self._min_order_quantity:
    logger.info("Delta %s for %s below minimum — skipping", delta, signal.symbol)
    return None

side = "buy" if signal.strength > Decimal(0) else "sell"
stop_price, take_profit_price = self._compute_exit_prices(signal, side)

req = OrderRequest(order_id=uuid4(), symbol=signal.symbol, side=side,
                   quantity=delta, ...)

async with self._db() as db:
    if stop_price or take_profit_price:
        order_status = await self._adapter.place_bracket_order(
            req, stop_price, take_profit_price, db
        )
    else:
        order_status = await self._adapter.place_order(req, db)

    # record signal_orders + commit
    ...

self._pending[signal.symbol] = self._pending.get(signal.symbol, Decimal("0")) + delta
return order_status
```

### 4. Migration 0005

**File:** `migrations/versions/0005_phase6.py`

Create `bracket_orders` table:

```sql
CREATE TABLE bracket_orders (
    id             TEXT PRIMARY KEY,
    order_id       TEXT NOT NULL REFERENCES orders(id),
    stop_ib_id     INTEGER,
    take_profit_ib_id INTEGER,
    stop_price     TEXT,
    take_profit_price TEXT,
    created_at     TEXT NOT NULL
);
CREATE INDEX ix_bracket_orders_order_id ON bracket_orders (order_id);
```

Add nullable columns to `signal_orders`:
```sql
ALTER TABLE signal_orders ADD COLUMN stop_price TEXT;
ALTER TABLE signal_orders ADD COLUMN take_profit_price TEXT;
```

Downgrade: drop `bracket_orders`, drop added columns (SQLite batch-alter pattern).

### 5. Strategy updates (optional, for demonstration)

**Files:** `strategies/ma_crossover.py`, `strategies/rsi_mean_reversion.py`

Both strategies can optionally set stop/take-profit from env vars:

```python
stop_loss_pct: Decimal | None = None       # MA_STOP_LOSS_PCT / RSI_STOP_LOSS_PCT
take_profit_pct: Decimal | None = None     # MA_TAKE_PROFIT_PCT / RSI_TAKE_PROFIT_PCT
```

If env vars are not set, fields remain `None` and the strategy behaves exactly as before.

---

## Data Flow

```
StrategyScheduler.tick()
  → strategy.on_bars(bars)
      → Signal(strength=0.7, reference_price=150.00,
                stop_loss_pct=5, take_profit_pct=10)
          → OrderManager.process_signal(signal)
              → reconcile _pending vs live positions
              → risk checks (unchanged)
              → target_qty = _compute_quantity()     # 140 shares
              → delta = 140 - held(0) - pending(0)  # = 140
              → stop_price  = 150 × 0.95 = 142.50
              → take_profit = 150 × 1.10 = 165.00
              → adapter.place_bracket_order(qty=140, stop=142.50, tp=165.00)
              → _pending["AAPL"] += 140
              ← next cycle: if positions["AAPL"].quantity >= 140 → clear pending
```

---

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `MA_STOP_LOSS_PCT` | `""` (disabled) | Stop-loss % for MA Crossover strategy |
| `MA_TAKE_PROFIT_PCT` | `""` (disabled) | Take-profit % for MA Crossover strategy |
| `RSI_STOP_LOSS_PCT` | `""` (disabled) | Stop-loss % for RSI strategy |
| `RSI_TAKE_PROFIT_PCT` | `""` (disabled) | Take-profit % for RSI strategy |

---

## Tests

### `tests/test_schemas.py` — Signal exit param tests

- `test_signal_stop_loss_pct_defaults_to_none`
- `test_signal_take_profit_pct_defaults_to_none`
- `test_signal_stop_loss_pct_accepts_decimal`
- `test_signal_take_profit_pct_accepts_decimal`
- `test_signal_stop_loss_pct_rejects_float`
- `test_signal_take_profit_pct_rejects_float`

### `tests/test_order_manager.py` — delta sizing + bracket routing

- `test_delta_sizing_no_pending_no_position` — target=200, held=0, pending=0 → delta=200
- `test_delta_sizing_with_pending` — target=200, pending=100, held=0 → delta=100
- `test_delta_sizing_with_held_position` — target=200, held=150, pending=0 → delta=50
- `test_delta_sizing_already_at_target_skips_signal` — held+pending >= target → returns None
- `test_pending_reconciliation_clears_on_fill` — positions show 200 held, pending was 200 → cleared
- `test_pending_reconciliation_partial_fill` — positions show 100, pending was 200 → not cleared
- `test_bracket_order_submitted_when_stop_loss_set` — `place_bracket_order` called
- `test_bracket_order_submitted_when_take_profit_set` — `place_bracket_order` called
- `test_plain_order_when_no_exit_params` — `place_order` called (no regression)
- `test_pending_incremented_after_bracket_order`

### `tests/test_exit_prices.py` — price computation

- `test_stop_price_buy_signal` — price=100, stop_loss_pct=5 → stop=95.00
- `test_take_profit_buy_signal` — price=100, take_profit_pct=10 → take_profit=110.00
- `test_stop_price_sell_signal` — price=100, stop_loss_pct=5 → stop=105.00
- `test_take_profit_sell_signal` — price=100, take_profit_pct=10 → take_profit=90.00
- `test_exit_prices_none_when_no_reference_price` — reference_price=None → (None, None)
- `test_exit_prices_none_when_no_pct_set` — both pcts None → (None, None)
- `test_stop_price_rounded_to_cents`

### `tests/test_broker_adapter.py` — bracket order submission

- `test_place_bracket_order_submits_three_ib_orders`
- `test_bracket_parent_transmit_false`
- `test_bracket_last_child_transmit_true`
- `test_bracket_children_have_correct_parent_id`
- `test_bracket_stop_is_sell_for_buy_parent`
- `test_bracket_stop_is_buy_for_sell_parent`

### `tests/test_migrations.py`

- `test_bracket_orders_table_created` — table exists after 0005 upgrade
- `test_signal_orders_has_stop_price_column` — column present after upgrade
- `test_0005_downgrade_removes_bracket_orders` — table gone after downgrade

---

## Known Limitations

- **`_pending` resets on app restart** — a restart while orders are in-flight will cause over-sizing on the next signal until the fill appears in live position data. Acceptable for Phase 6; a persistent pending table can be added later.
- **Bracket order exit prices are fixed at entry** — no trailing stops. A monitoring loop for trailing would be Phase 7+.
- **Short selling stop/take-profit** — inverted prices are computed correctly but IB short-sell permissions must be configured separately in the IB Gateway.
- **`check_position_size` in RiskGuard still checks only filled positions** — with pending tracker now in `OrderManager`, the risk guard gap (briefly exceeding max_position_pct) is partially mitigated but the guard itself is not updated. Full fix is a future phase.

---

## Verification

```bash
uv run pytest
uv run ruff check src/
uv run alembic upgrade head
```

Manual check:
1. Start app, promote a strategy to live
2. Set `MA_STOP_LOSS_PCT=5` and `MA_TAKE_PROFIT_PCT=10` env vars
3. Trigger `POST /strategy/ma-crossover-aapl/run`
4. Inspect logs for "Placing bracket order: qty=X, stop=Y, tp=Z"
5. Verify IB Gateway shows parent order + two child orders linked by `parentId`
6. Trigger the same strategy again before fill — confirm delta order (not full size) submitted
