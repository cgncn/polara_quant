"""Tests for BacktestService against an in-memory SQLite database."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polara.backtester.schemas import BacktestResult
from polara.backtester.service import BacktestService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def db_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE backtest_results (
                id TEXT PRIMARY KEY,
                strategy_id TEXT NOT NULL,
                run_at TEXT NOT NULL,
                bar_size TEXT NOT NULL,
                num_bars INTEGER NOT NULL,
                sharpe_ratio TEXT NOT NULL,
                max_drawdown_pct TEXT NOT NULL,
                win_rate_pct TEXT NOT NULL,
                total_return_pct TEXT NOT NULL,
                num_trades INTEGER NOT NULL,
                passed INTEGER NOT NULL CHECK (passed IN (0, 1)),
                notes TEXT,
                sortino_ratio TEXT DEFAULT '0',
                calmar_ratio TEXT DEFAULT '0',
                profit_factor TEXT DEFAULT '0',
                avg_trade_pnl TEXT DEFAULT '0',
                reward_risk_ratio TEXT DEFAULT '0'
            )
        """))
    return async_sessionmaker(engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_result(
    strategy_id: str = "s1",
    passed: bool = True,
    run_at: datetime | None = None,
    notes: str | None = None,
) -> BacktestResult:
    return BacktestResult(
        strategy_id=strategy_id,
        run_at=run_at or datetime.now(UTC),
        bar_size="5 mins",
        num_bars=100,
        sharpe_ratio=Decimal("1.2"),
        max_drawdown_pct=Decimal("5.5"),
        win_rate_pct=Decimal("60"),
        total_return_pct=Decimal("15.3"),
        num_trades=10,
        passed=passed,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_and_get_round_trip(db_factory):
    """save() followed by get_results() returns all fields correctly."""
    svc = BacktestService(db_factory)
    original = make_result(strategy_id="s1", passed=True)
    await svc.save(original)

    results = await svc.get_results("s1")
    assert len(results) == 1
    got = results[0]

    assert got.strategy_id == original.strategy_id
    assert got.bar_size == original.bar_size
    assert got.num_bars == original.num_bars
    assert got.sharpe_ratio == original.sharpe_ratio
    assert got.max_drawdown_pct == original.max_drawdown_pct
    assert got.win_rate_pct == original.win_rate_pct
    assert got.total_return_pct == original.total_return_pct
    assert got.num_trades == original.num_trades
    assert got.passed == original.passed
    assert got.notes == original.notes


@pytest.mark.asyncio
async def test_has_passing_result_true(db_factory):
    """has_passing_result returns True when a passing result exists."""
    svc = BacktestService(db_factory)
    await svc.save(make_result(strategy_id="s1", passed=True))

    assert await svc.has_passing_result("s1") is True


@pytest.mark.asyncio
async def test_has_passing_result_false_empty_db(db_factory):
    """has_passing_result returns False when no results exist."""
    svc = BacktestService(db_factory)
    assert await svc.has_passing_result("nonexistent") is False


@pytest.mark.asyncio
async def test_has_passing_result_false_only_failing(db_factory):
    """has_passing_result returns False when only failing results exist."""
    svc = BacktestService(db_factory)
    await svc.save(make_result(strategy_id="s1", passed=False))

    assert await svc.has_passing_result("s1") is False


@pytest.mark.asyncio
async def test_get_results_limit_respected(db_factory):
    """get_results(limit=3) returns at most 3 results even when 5 are saved."""
    svc = BacktestService(db_factory)
    for _ in range(5):
        await svc.save(make_result(strategy_id="s1"))

    results = await svc.get_results("s1", limit=3)
    assert len(results) == 3


@pytest.mark.asyncio
async def test_get_results_ordered_newest_first(db_factory):
    """Results are returned ordered by run_at descending (newest first)."""
    svc = BacktestService(db_factory)
    now = datetime.now(UTC)
    old = make_result(strategy_id="s1", run_at=now - timedelta(hours=2))
    new = make_result(strategy_id="s1", run_at=now)

    await svc.save(old)
    await svc.save(new)

    results = await svc.get_results("s1")
    assert len(results) == 2
    # Newest first: run_at of first result should be >= second
    assert results[0].run_at >= results[1].run_at


@pytest.mark.asyncio
async def test_passed_false_serialised_correctly(db_factory):
    """A result saved with passed=False is retrieved with passed=False."""
    svc = BacktestService(db_factory)
    await svc.save(make_result(strategy_id="s1", passed=False))

    results = await svc.get_results("s1")
    assert len(results) == 1
    assert results[0].passed is False
