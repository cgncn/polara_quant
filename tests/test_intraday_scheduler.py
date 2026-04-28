"""Tests for IntradayScheduler."""
import pytest
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from polara.research_engine.intraday_scheduler import IntradayScheduler
from polara.schemas.signals import Signal


def make_bar(symbol: str = "AAPL"):
    from polara.schemas.market import Bar
    return Bar(
        symbol=symbol,
        timestamp=datetime.now(UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=1000,
    )


def make_strategy(strategy_id: str, bar_size: str, symbol: str = "AAPL"):
    s = MagicMock()
    s.strategy_id = strategy_id
    s.symbol = symbol
    s.bars_needed = 10
    s.bar_size = bar_size
    s.on_bars = MagicMock(return_value=None)
    return s


def make_scheduler(strategies: list):
    mock_svc = AsyncMock()
    mock_svc.get_bars = AsyncMock(return_value=[make_bar()])
    registry = MagicMock()
    registry.get_all = MagicMock(return_value=strategies)
    mock_manager = AsyncMock()
    mock_manager.process_signal = AsyncMock(return_value=None)
    scheduler = IntradayScheduler(
        market_data_svc=mock_svc,
        registry=registry,
        order_manager=mock_manager,
        interval_seconds=60,
    )
    return scheduler


@pytest.mark.asyncio
async def test_intraday_scheduler_calls_on_bars_for_15min():
    strategy = make_strategy("s1", "15 mins")
    scheduler = make_scheduler([strategy])
    await scheduler._run_once()
    strategy.on_bars.assert_called_once()


@pytest.mark.asyncio
async def test_intraday_scheduler_calls_on_bars_for_30min():
    strategy = make_strategy("s2", "30 mins")
    scheduler = make_scheduler([strategy])
    await scheduler._run_once()
    strategy.on_bars.assert_called_once()


@pytest.mark.asyncio
async def test_intraday_scheduler_skips_1hour_strategies():
    strategy = make_strategy("s3", "1 hour")
    scheduler = make_scheduler([strategy])
    await scheduler._run_once()
    strategy.on_bars.assert_not_called()


@pytest.mark.asyncio
async def test_intraday_scheduler_skips_1day_strategies():
    strategy = make_strategy("s4", "1 day")
    scheduler = make_scheduler([strategy])
    await scheduler._run_once()
    strategy.on_bars.assert_not_called()


@pytest.mark.asyncio
async def test_intraday_scheduler_submits_signal_from_intraday_strategy():
    signal = Signal(
        signal_id=uuid4(),
        strategy_id="s5",
        symbol="AAPL",
        strength=Decimal("1"),
        generated_at=datetime.now(UTC),
    )
    strategy = make_strategy("s5", "15 mins")
    strategy.on_bars = MagicMock(return_value=signal)

    mock_svc = AsyncMock()
    mock_svc.get_bars = AsyncMock(return_value=[make_bar()])
    registry = MagicMock()
    registry.get_all = MagicMock(return_value=[strategy])
    mock_manager = AsyncMock()
    mock_manager.process_signal = AsyncMock(return_value=None)

    scheduler = IntradayScheduler(
        market_data_svc=mock_svc,
        registry=registry,
        order_manager=mock_manager,
        interval_seconds=60,
    )
    await scheduler._run_once()
    mock_manager.process_signal.assert_called_once_with(signal)


@pytest.mark.asyncio
async def test_intraday_scheduler_continues_after_risk_violation():
    """_run_once must not abort when a strategy raises RiskViolationError."""
    from polara.risk_guard.exceptions import RiskViolationError

    signal1 = Signal(
        signal_id=uuid4(),
        strategy_id="s6",
        symbol="AAPL",
        strength=Decimal("1"),
        generated_at=datetime.now(UTC),
    )
    signal2 = Signal(
        signal_id=uuid4(),
        strategy_id="s7",
        symbol="AAPL",
        strength=Decimal("1"),
        generated_at=datetime.now(UTC),
    )

    strategy1 = make_strategy("s6", "15 mins")
    strategy1.on_bars = MagicMock(return_value=signal1)
    strategy2 = make_strategy("s7", "15 mins")
    strategy2.on_bars = MagicMock(return_value=signal2)

    mock_svc = AsyncMock()
    mock_svc.get_bars = AsyncMock(return_value=[make_bar()])
    registry = MagicMock()
    registry.get_all = MagicMock(return_value=[strategy1, strategy2])
    mock_manager = AsyncMock()
    # First call raises, second succeeds
    mock_manager.process_signal = AsyncMock(
        side_effect=[RiskViolationError("test"), None]
    )

    scheduler = IntradayScheduler(
        market_data_svc=mock_svc,
        registry=registry,
        order_manager=mock_manager,
        interval_seconds=60,
    )
    # Should not raise
    await scheduler._run_once()
    # Both strategies were attempted
    assert mock_manager.process_signal.call_count == 2
