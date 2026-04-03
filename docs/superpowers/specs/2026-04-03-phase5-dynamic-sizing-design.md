# Phase 5: Dynamic Order Sizing

## Context

Every order in Phase 3–4 was hardcoded to `quantity=Decimal("1")`. This means a weak signal (strength 0.1) and a strong signal (strength 0.9) produce identical trades — a significant loss of information. Phase 5 uses `signal.strength` and the live account NAV to compute a proportional order size, making every existing strategy immediately smarter without touching strategy logic.

## Goal

Replace the hardcoded `quantity=1` in `OrderManager` with:

```
quantity = floor(NAV × (max_position_pct / 100) × |strength| / reference_price)
```

A full-strength signal at a 10% position cap on a $100k account buying a $50 stock → 200 shares.
A half-strength signal → 100 shares.

## Changes

### 1. `Signal` schema — add `reference_price`

**File:** `src/polara/schemas/signals.py`

```python
reference_price: Decimal | None = None
```

Optional (not required) so existing test fixtures and external callers don't break immediately. Strategies always set it from `bars[-1].close`. If `None` at order time, falls back to `quantity=1` with a warning log.

### 2. `RiskGuard` — expose `max_position_pct` property

**File:** `src/polara/risk_guard/guard.py`

Add a read-only property:

```python
@property
def max_position_pct(self) -> Decimal:
    return self._max_position_pct
```

`OrderManager` already holds a `RiskGuard` reference — no new dependency needed.

### 3. `OrderManager` — dynamic sizing + minimum quantity guard

**File:** `src/polara/order_manager/manager.py`

Constructor gains one new optional param sourced from env:

```python
min_order_quantity: Decimal = Decimal("1")
```

Sizing logic replaces the hardcoded `quantity=Decimal("1")`:

```python
if signal.reference_price and signal.reference_price > Decimal(0):
    target_notional = (
        account.net_liquidation
        * (self._risk_guard.max_position_pct / Decimal("100"))
        * abs(signal.strength)
    )
    quantity = (target_notional / signal.reference_price).to_integral_value(
        rounding=ROUND_DOWN
    )
else:
    logger.warning(
        "Signal for %s has no reference_price — falling back to quantity=1",
        signal.symbol,
    )
    quantity = Decimal("1")

if quantity < self._min_order_quantity:
    logger.info(
        "Computed quantity %s for %s is below minimum %s — skipping signal",
        quantity, signal.symbol, self._min_order_quantity,
    )
    return None
```

**Minimum quantity guard:** `MIN_ORDER_QUANTITY` env var (default `"1"`). Prevents submitting fractional or uneconomically small orders. Applies to both dynamic and fallback paths.

### 4. Strategy updates — set `reference_price`

**Files:** `strategies/ma_crossover.py`, `strategies/rsi_mean_reversion.py`

Both strategies set `reference_price=bars[-1].close` when constructing the `Signal`:

```python
return Signal(
    signal_id=uuid4(),
    strategy_id=self.strategy_id,
    symbol=self.symbol,
    strength=strength,
    generated_at=datetime.now(UTC),
    reference_price=bars[-1].close,   # ← new
)
```

### 5. `main.py` wiring

Pass `min_order_quantity` to `OrderManager`:

```python
order_manager = OrderManager(
    broker_adapter=adapter,
    risk_guard=risk_guard,
    db_session_factory=AsyncSessionLocal,
    status_service=status_service,
    min_order_quantity=Decimal(os.environ.get("MIN_ORDER_QUANTITY", "1")),
)
```

### 6. Backtester — unchanged (known limitation)

The backtester still simulates 1-unit trades. Dynamic sizing is a live-trading concern; Sharpe ratio, drawdown, and win rate computed from relative equity moves remain valid as comparative metrics. This limitation should be addressed in a future phase that adds position-aware backtesting.

## Data Flow

```
strategy.on_bars(bars)
  → Signal(strength=0.7, reference_price=bars[-1].close)
      → OrderManager.process_signal(signal)
          → account = adapter.get_account()           # NAV
          → target_notional = NAV × 10% × 0.7        # = 7% of NAV
          → quantity = floor(target_notional / price) # e.g. 140 shares
          → if quantity < min_order_quantity → skip
          → RiskGuard checks (existing position check, daily loss)
          → adapter.place_order(OrderRequest(quantity=140))
```

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `MIN_ORDER_QUANTITY` | `"1"` | Skip signal if computed quantity is below this |
| `RISK_MAX_POSITION_PCT` | `"10"` | Already exists; now also drives sizing |

## Tests

### `tests/test_order_manager.py` — new cases

- `test_dynamic_sizing_full_strength` — strength=1.0, NAV=100000, pct=10, price=50 → quantity=200
- `test_dynamic_sizing_half_strength` — strength=0.5 → quantity=100
- `test_dynamic_sizing_no_reference_price_falls_back_to_one` — reference_price=None → quantity=1
- `test_dynamic_sizing_below_minimum_returns_none` — computed qty=0 → returns None, no order
- `test_dynamic_sizing_custom_minimum` — MIN_ORDER_QUANTITY=50, computed qty=30 → skip
- `test_dynamic_sizing_quantity_is_decimal` — assert isinstance(quantity, Decimal)
- `test_dynamic_sizing_uses_floor_not_round` — e.g. 200.9 → 200, not 201

### `tests/test_risk_guard.py` — one new case

- `test_max_position_pct_property_exposed` — assert guard.max_position_pct == expected

### `tests/test_schemas.py` — minimal

- Existing Signal tests remain valid (reference_price is optional, defaults to None)
- Add: `test_signal_reference_price_is_decimal` — verify Decimal type accepted

### `tests/test_research_engine.py` / `tests/test_rsi_strategy.py`

- Update signal assertions to check `signal.reference_price == bars[-1].close`

## Verification

```bash
uv run pytest
uv run ruff check src/
```

Manual check:
1. Start app, ensure a strategy is live
2. Trigger `POST /strategy/{id}/run` — inspect logs for "Computed quantity: X shares"
3. Verify order in `GET /broker/orders` has quantity > 1 (for non-trivial account sizes)

## Known Limitations

- Backtester still uses 1-unit trades; dynamic sizing is not reflected in backtest metrics
- `check_position_size` in `RiskGuard` checks existing position, not the proposed order — adding to a position could briefly exceed `max_position_pct` until the next fill is recorded. This is addressed in a future portfolio rebalancer phase.
- No delta sizing: if we hold 5% and size to 10%, we order the full 10% notional rather than the 5% delta. Oversizing is caught by the risk guard on the next cycle.
