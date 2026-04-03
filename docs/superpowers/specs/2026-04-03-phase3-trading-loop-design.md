# Polara Quant — Phase 3 Design Spec: Full Trading Loop

**Date:** 2026-04-03
**Phase:** 3 (Full Trading Loop)
**Status:** Active

---

## What Phase 3 Builds

Four new modules that complete the paper-trading loop on top of the Phase 2 broker adapter:

```
[StrategyScheduler — asyncio background task, every N seconds]
  └─ for each registered strategy:
       1. MarketDataService.get_bars(symbol, n, bar_size)
            └─ IBFetcher.fetch_bars()   → IB Gateway reqHistoricalData → list[Bar]
            └─ BarStore.upsert()        → DuckDB  (data/market_data.duckdb)
            └─ BarStore.query()         → list[Bar] (latest n bars)
       2. strategy.on_bars(bars)        → Signal | None
       3. RiskGuard.check_daily_loss(account)        → ok | RiskViolationError
       4. RiskGuard.check_position_size(signal, positions, account) → ok | RiskViolationError
       5. OrderManager.process_signal(signal) → OrderStatus
            └─ BrokerAdapter.place_order()  ← already built in Phase 2
            └─ INSERT INTO signal_orders
```

## Module Map

```
src/polara/
├── market_data/
│   ├── __init__.py
│   ├── fetcher.py          # IBFetcher — wraps ib_async reqHistoricalData/reqTickers
│   ├── store.py            # BarStore — DuckDB reads/writes
│   └── service.py          # MarketDataService — orchestrates fetcher + store
├── research_engine/
│   ├── __init__.py
│   ├── base.py             # Strategy ABC
│   ├── registry.py         # StrategyRegistry
│   └── strategies/
│       ├── __init__.py
│       └── ma_crossover.py # MACrossoverStrategy
├── risk_guard/
│   ├── __init__.py
│   ├── exceptions.py       # RiskViolationError
│   └── guard.py            # RiskGuard
├── order_manager/
│   ├── __init__.py
│   └── manager.py          # OrderManager
└── api/routes/
    ├── market_data.py      # GET /market-data/bars/{symbol}, GET /market-data/quote/{symbol}
    └── strategy.py         # GET /strategy/list, POST /strategy/run/{strategy_id}

migrations/versions/
└── 0003_phase3.py          # signal_orders table
```

## New Environment Variables

```
MARKET_DATA_DB_PATH=data/market_data.duckdb
STRATEGY_INTERVAL_SECONDS=60
RISK_MAX_POSITION_PCT=10
RISK_MAX_DAILY_LOSS_PCT=5
MA_STRATEGY_ID=ma-crossover-aapl
MA_STRATEGY_SYMBOL=AAPL
MA_FAST_PERIOD=10
MA_SLOW_PERIOD=50
MA_QUANTITY=1
MA_BAR_SIZE=5 mins
```

## Non-Negotiable Rules

1. No `float` for prices, quantities, P&L. Use `Decimal`.
2. All datetimes UTC-aware.
3. Pydantic `strict=True` on all new models.
4. Postgres-compatible SQL only.
5. Only `polara.broker` + `polara.market_data` talk to IB Gateway (via shared IBClient.ib).

## Data Flow

```
Scheduler loop (every STRATEGY_INTERVAL_SECONDS):
  for strategy in registry:
    bars = market_data_svc.get_bars(symbol, n=bars_needed, bar_size)
    signal = strategy.on_bars(bars)
    if signal:
      order_manager.process_signal(signal)
        → risk_guard.check_daily_loss(account)
        → risk_guard.check_position_size(signal, positions, account)
        → broker_adapter.place_order(order_request, db)
        → INSERT INTO signal_orders
```

## Risk Guard

Two checks before any order is submitted:
1. **Max position size**: current position notional / NAV ≤ max_position_pct (default 10%)
2. **Daily loss halt**: if (unrealised_pnl + realised_pnl) / NAV drops below -max_daily_loss_pct (default 5%), halt all trading until next UTC day

## Strategy: MA Crossover

First strategy implementation:
- `fast_period` and `slow_period` configurable via env vars
- Emits `Signal(strength=+1)` when fast SMA crosses above slow SMA
- Emits `Signal(strength=-1)` when fast SMA crosses below slow SMA
- Returns `None` when insufficient bars or no crossover
- All arithmetic uses `Decimal` (no float for price calculations)

## Database Addition

Migration 0003 adds `signal_orders` table:
- Links `signal_id` → `order_id` for audit trail
- Stores strategy_id, symbol, signal_strength (as TEXT)
- Postgres-compatible schema

## Phase 3 Exit Criteria

- [ ] `GET /market-data/bars/AAPL` returns bars from IB
- [ ] `GET /strategy/list` shows registered strategies
- [ ] `POST /strategy/run/ma-crossover-aapl` triggers evaluation and returns 200/204
- [ ] Scheduler auto-runs every 60s in background
- [ ] Risk guard rejects breaching trades (logs warning, no order)
- [ ] All tests pass: `uv run pytest`
- [ ] No ruff errors: `uv run ruff check src/`
