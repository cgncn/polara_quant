# Polara Quant — Claude Code Rules

## Non-Negotiable Operating Rules
1. **Never use `float` for money, prices, commissions, or quantities.** Always use `Decimal`.
2. **All datetimes must be UTC-aware.** Use `datetime.now(UTC)` or `datetime(..., tzinfo=UTC)`. Never `datetime.utcnow()` (naive).
3. **Pydantic models use `strict=True`.** No silent type coercion.
4. **SQLite now, Postgres-compatible always.** No SQLite-specific SQL syntax.
5. **One service owns the broker adapter.** Nothing else talks to IB Gateway directly.
6. **No strategy self-promotes.** Promotion gates are always manual.

## Test Requirements
- All new modules must have tests in `tests/`
- Run `uv run pytest` before marking any task complete
- Run `uv run ruff check src/` before committing

## Phase Status
Current phase: Phase 2 (Broker Adapter)
Do NOT build: order_manager, risk_guard, research_engine, validator, market_data_streaming
These are Phase 3+ work.
