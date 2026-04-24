"""Tests for research_engine base class and registry."""
from datetime import datetime, UTC
from decimal import Decimal
import pytest

from polara.research_engine.base import Strategy
from polara.research_engine.registry import StrategyRegistry
from polara.schemas.market import Bar
from polara.schemas.signals import Signal


def make_bar(close: str = "170.00", ts_offset_minutes: int = 0) -> Bar:
    from datetime import timedelta
    # Use now() so the scheduler's stale-bar guard (2h) never filters out test bars.
    return Bar(
        symbol="AAPL",
        timestamp=datetime.now(UTC) + timedelta(minutes=ts_offset_minutes * 5),
        open=Decimal("170.00"),
        high=Decimal("171.00"),
        low=Decimal("169.50"),
        close=Decimal(close),
        volume=1000,
    )


class ConcreteStrategy(Strategy):
    strategy_id = "test-strategy"
    symbol = "AAPL"
    bars_needed = 10
    bar_size = "5 mins"

    def on_bars(self, bars: list[Bar]) -> Signal | None:
        return None


def test_strategy_abc_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        Strategy()


def test_concrete_strategy_can_be_instantiated():
    s = ConcreteStrategy()
    assert s.strategy_id == "test-strategy"
    assert s.symbol == "AAPL"


def test_registry_register_and_get_all():
    registry = StrategyRegistry()
    s = ConcreteStrategy()
    registry.register(s)
    strategies = registry.get_all()
    assert len(strategies) == 1
    assert strategies[0] is s


def test_registry_get_by_id():
    registry = StrategyRegistry()
    s = ConcreteStrategy()
    registry.register(s)
    assert registry.get("test-strategy") is s


def test_registry_get_unknown_raises():
    registry = StrategyRegistry()
    with pytest.raises(KeyError):
        registry.get("unknown-id")


def test_registry_register_duplicate_raises():
    registry = StrategyRegistry()
    registry.register(ConcreteStrategy())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(ConcreteStrategy())


# ── MACrossoverStrategy tests ───────────────────────────────────────────────
from polara.research_engine.strategies.ma_crossover import MACrossoverStrategy


def make_bars_crossover_up(n: int = 60, fast: int = 5, slow: int = 20) -> list[Bar]:
    """Flat baseline then single price spike on the last bar → fast MA crosses above slow MA."""
    from datetime import timedelta
    base = datetime(2026, 4, 3, 9, 30, tzinfo=UTC)
    bars = []
    for i in range(n):
        # All bars flat except the very last, which spikes sharply.
        # At offset=1 (prev): fast==slow (both 100). At offset=0 (curr): fast > slow.
        price = Decimal("200") if i == n - 1 else Decimal("100")
        bars.append(Bar(
            symbol="AAPL",
            timestamp=base + timedelta(minutes=5 * i),
            open=price, high=price + Decimal("1"), low=price - Decimal("1"),
            close=price, volume=1000,
        ))
    return bars


def make_bars_crossover_down(n: int = 60, fast: int = 5, slow: int = 20) -> list[Bar]:
    """Flat baseline then single price drop on the last bar → fast MA crosses below slow MA."""
    from datetime import timedelta
    base = datetime(2026, 4, 3, 9, 30, tzinfo=UTC)
    bars = []
    for i in range(n):
        # All bars flat except the very last, which drops sharply.
        # At offset=1 (prev): fast==slow (both 100). At offset=0 (curr): fast < slow.
        price = Decimal("10") if i == n - 1 else Decimal("100")
        bars.append(Bar(
            symbol="AAPL",
            timestamp=base + timedelta(minutes=5 * i),
            open=price, high=price + Decimal("1"), low=price - Decimal("1"),
            close=price, volume=1000,
        ))
    return bars


def test_ma_crossover_buy_signal_on_fast_crosses_above():
    strategy = MACrossoverStrategy(
        strategy_id="test-ma",
        symbol="AAPL",
        fast_period=5,
        slow_period=20,
        quantity=Decimal("1"),
        bar_size="5 mins",
    )
    bars = make_bars_crossover_up()
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.strength == Decimal("1")
    assert signal.symbol == "AAPL"
    assert signal.strategy_id == "test-ma"
    assert signal.reference_price == bars[-1].close


def test_ma_crossover_sell_signal_on_fast_crosses_below():
    strategy = MACrossoverStrategy(
        strategy_id="test-ma",
        symbol="AAPL",
        fast_period=5,
        slow_period=20,
        quantity=Decimal("1"),
        bar_size="5 mins",
    )
    bars = make_bars_crossover_down()
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.strength == Decimal("-1")
    assert signal.reference_price == bars[-1].close


def test_ma_crossover_no_signal_when_no_crossover():
    from datetime import timedelta
    base = datetime(2026, 4, 3, 9, 30, tzinfo=UTC)
    # Flat price — no crossover
    bars = [
        Bar(
            symbol="AAPL",
            timestamp=base + timedelta(minutes=5 * i),
            open=Decimal("100"), high=Decimal("101"), low=Decimal("99"),
            close=Decimal("100"), volume=1000,
        )
        for i in range(60)
    ]
    strategy = MACrossoverStrategy(
        strategy_id="test-ma", symbol="AAPL",
        fast_period=5, slow_period=20,
        quantity=Decimal("1"), bar_size="5 mins",
    )
    assert strategy.on_bars(bars) is None


def test_ma_crossover_no_signal_insufficient_bars():
    strategy = MACrossoverStrategy(
        strategy_id="test-ma", symbol="AAPL",
        fast_period=5, slow_period=20,
        quantity=Decimal("1"), bar_size="5 mins",
    )
    bars = [make_bar(str(100 + i), i) for i in range(10)]  # only 10, need 21
    assert strategy.on_bars(bars) is None


def test_ma_crossover_signal_has_utc_timestamp():
    strategy = MACrossoverStrategy(
        strategy_id="test-ma", symbol="AAPL",
        fast_period=5, slow_period=20,
        quantity=Decimal("1"), bar_size="5 mins",
    )
    bars = make_bars_crossover_up()
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.generated_at.tzinfo is not None


def test_ma_crossover_bars_needed_is_slow_period_plus_one():
    strategy = MACrossoverStrategy(
        strategy_id="test-ma", symbol="AAPL",
        fast_period=10, slow_period=50,
        quantity=Decimal("1"), bar_size="5 mins",
    )
    assert strategy.bars_needed == 51  # slow_period + 1


def test_ma_crossover_signal_includes_stop_loss_pct():
    """stop_loss_pct on strategy propagates to emitted Signal."""
    strategy = MACrossoverStrategy(
        strategy_id="test-ma",
        symbol="AAPL",
        fast_period=5,
        slow_period=20,
        quantity=Decimal("1"),
        bar_size="5 mins",
        stop_loss_pct=Decimal("5"),
    )
    bars = make_bars_crossover_up()
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.stop_loss_pct == Decimal("5")


def test_ma_crossover_signal_includes_take_profit_pct():
    """take_profit_pct on strategy propagates to emitted Signal."""
    strategy = MACrossoverStrategy(
        strategy_id="test-ma",
        symbol="AAPL",
        fast_period=5,
        slow_period=20,
        quantity=Decimal("1"),
        bar_size="5 mins",
        take_profit_pct=Decimal("10"),
    )
    bars = make_bars_crossover_up()
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.take_profit_pct == Decimal("10")


def test_ma_crossover_signal_stop_loss_none_when_not_set():
    """stop_loss_pct defaults to None on Signal when not configured."""
    strategy = MACrossoverStrategy(
        strategy_id="test-ma",
        symbol="AAPL",
        fast_period=5,
        slow_period=20,
        quantity=Decimal("1"),
        bar_size="5 mins",
    )
    bars = make_bars_crossover_up()
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.stop_loss_pct is None


# ── StrategyScheduler tests ─────────────────────────────────────────────────
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from polara.research_engine.scheduler import StrategyScheduler
from polara.risk_guard.exceptions import RiskViolationError


@pytest.mark.asyncio
async def test_scheduler_run_once_calls_get_bars_and_on_bars():
    mock_svc = AsyncMock()
    mock_svc.get_bars = AsyncMock(return_value=[make_bar()])

    strategy = MagicMock()
    strategy.strategy_id = "test"
    strategy.symbol = "AAPL"
    strategy.bars_needed = 51
    strategy.bar_size = "5 mins"
    strategy.on_bars = MagicMock(return_value=None)

    registry = MagicMock()
    registry.get_all = MagicMock(return_value=[strategy])

    mock_manager = AsyncMock()
    scheduler = StrategyScheduler(
        market_data_svc=mock_svc,
        registry=registry,
        order_manager=mock_manager,
        interval_seconds=60,
    )
    await scheduler._run_once()

    mock_svc.get_bars.assert_called_once_with("AAPL", n=51, bar_size="5 mins")
    strategy.on_bars.assert_called_once()


@pytest.mark.asyncio
async def test_scheduler_submits_signal_when_generated():
    mock_svc = AsyncMock()
    mock_svc.get_bars = AsyncMock(return_value=[make_bar()] * 51)

    signal = Signal(
        signal_id=uuid4(),
        strategy_id="test",
        symbol="AAPL",
        strength=Decimal("1"),
        generated_at=datetime.now(UTC),
    )
    strategy = MagicMock()
    strategy.strategy_id = "test"
    strategy.symbol = "AAPL"
    strategy.bars_needed = 51
    strategy.bar_size = "5 mins"
    strategy.on_bars = MagicMock(return_value=signal)

    registry = MagicMock()
    registry.get_all = MagicMock(return_value=[strategy])

    mock_manager = AsyncMock()
    mock_manager.process_signal = AsyncMock(return_value=None)

    scheduler = StrategyScheduler(
        market_data_svc=mock_svc,
        registry=registry,
        order_manager=mock_manager,
        interval_seconds=60,
    )
    await scheduler._run_once()
    mock_manager.process_signal.assert_called_once_with(signal)


@pytest.mark.asyncio
async def test_scheduler_continues_after_exception():
    """Scheduler logs and continues if a strategy raises unexpectedly."""
    mock_svc = AsyncMock()
    mock_svc.get_bars = AsyncMock(side_effect=Exception("IB error"))

    strategy = MagicMock()
    strategy.strategy_id = "test"
    strategy.symbol = "AAPL"
    strategy.bars_needed = 51
    strategy.bar_size = "5 mins"

    registry = MagicMock()
    registry.get_all = MagicMock(return_value=[strategy])

    mock_manager = AsyncMock()
    scheduler = StrategyScheduler(
        market_data_svc=mock_svc,
        registry=registry,
        order_manager=mock_manager,
        interval_seconds=60,
    )
    # Should not raise
    await scheduler._run_once()
