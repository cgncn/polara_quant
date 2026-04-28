"""Tests for CalibrationService against an in-memory SQLite database."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polara.calibration.schemas import CalibrationResult
from polara.calibration.service import CalibrationService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def db_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    svc = CalibrationService(factory)
    await svc.migrate()
    return factory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_result(
    strategy_id: str = "s1",
    calibrated_at: datetime | None = None,
    rolling_sharpe: str = "1.2",
    size_multiplier: str = "1.5",
    improvement: str = "0.3",
) -> CalibrationResult:
    return CalibrationResult(
        strategy_id=strategy_id,
        calibrated_at=calibrated_at or datetime.now(UTC),
        bar_size="5 mins",
        lookback_bars=200,
        rolling_sharpe=Decimal(rolling_sharpe),
        size_multiplier=Decimal(size_multiplier),
        prev_params={"threshold": "0.001"},
        best_params={"threshold": "0.002"},
        param_sharpe_improvement=Decimal(improvement),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_then_latest_round_trip(db_factory):
    """save() followed by latest() returns the saved result."""
    svc = CalibrationService(db_factory)
    original = make_result(strategy_id="s1")
    await svc.save(original)

    got = await svc.latest("s1")
    assert got is not None
    assert got.strategy_id == original.strategy_id
    assert got.bar_size == original.bar_size
    assert got.lookback_bars == original.lookback_bars
    assert got.rolling_sharpe == original.rolling_sharpe
    assert got.size_multiplier == original.size_multiplier
    assert got.prev_params == original.prev_params
    assert got.best_params == original.best_params
    assert got.param_sharpe_improvement == original.param_sharpe_improvement


@pytest.mark.asyncio
async def test_history_returns_descending_order(db_factory):
    """history() returns results ordered newest-first."""
    svc = CalibrationService(db_factory)
    now = datetime.now(UTC)
    old = make_result(strategy_id="s1", calibrated_at=now - timedelta(hours=2))
    new = make_result(strategy_id="s1", calibrated_at=now)

    await svc.save(old)
    await svc.save(new)

    results = await svc.history("s1")
    assert len(results) == 2
    assert results[0].calibrated_at >= results[1].calibrated_at


@pytest.mark.asyncio
async def test_latest_returns_none_when_no_results(db_factory):
    """latest() returns None when no records exist for the strategy."""
    svc = CalibrationService(db_factory)
    assert await svc.latest("nonexistent") is None


@pytest.mark.asyncio
async def test_history_limit_respected(db_factory):
    """history(limit=2) returns at most 2 results."""
    svc = CalibrationService(db_factory)
    for _ in range(4):
        await svc.save(make_result(strategy_id="s1"))

    results = await svc.history("s1", limit=2)
    assert len(results) == 2
