# Polara Quant — Claude Code Rules

## Non-Negotiable Operating Rules
1. **Never use `float` for money, prices, commissions, or quantities.** Always use `Decimal`. The sole exception is values passed directly to `ib_async` order constructors (`LimitOrder`, `MarketOrder`) which require `float` at the IB API boundary — convert from `Decimal` via `float()` only there.
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
Current phase: Phase 3 (Full Trading Loop)
Do NOT build: validator, live-trading promotion
These are Phase 4+ work.
