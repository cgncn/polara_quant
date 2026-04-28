"""Tests for ConfluentScheduler."""
import pytest
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from polara.research_engine.confluent_scheduler import ConfluentScheduler
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


def make_signal(strategy_id: str, strength: str) -> Signal:
    return Signal(
        signal_id=uuid4(),
        strategy_id=strategy_id,
        symbol="AAPL",
        strength=Decimal(strength),
        generated_at=datetime.now(UTC),
    )


def make_strategy(strategy_id: str, signal: Signal | None = None):
    s = MagicMock()
    s.strategy_id = strategy_id
    s.symbol = "AAPL"
    s.bars_needed = 10
    s.bar_size = "1 day"
    s.on_bars = MagicMock(return_value=signal)
    return s


def make_scheduler(
    long_term_strategies: dict,
    intraday_strategies: dict,
    min_bias_strength: str = "0",
):
    mock_svc = AsyncMock()
    mock_svc.get_bars = AsyncMock(return_value=[make_bar()])

    all_strategies = {**long_term_strategies, **intraday_strategies}

    registry = MagicMock()
    registry.get = MagicMock(side_effect=lambda sid: all_strategies[sid])

    mock_manager = AsyncMock()
    mock_manager.process_signal = AsyncMock(return_value=None)

    return ConfluentScheduler(
        market_data_svc=mock_svc,
        registry=registry,
        order_manager=mock_manager,
        long_term_ids=list(long_term_strategies.keys()),
        intraday_ids=list(intraday_strategies.keys()),
        min_bias_strength=Decimal(min_bias_strength),
    ), mock_manager


@pytest.mark.asyncio
async def test_compute_bias_bullish_when_avg_strength_positive():
    signal = make_signal("lt1", "0.8")
    strategy = make_strategy("lt1", signal)
    scheduler, _ = make_scheduler({"lt1": strategy}, {})
    bias = await scheduler._compute_bias()
    assert bias == "bullish"


@pytest.mark.asyncio
async def test_compute_bias_bearish_when_avg_strength_negative():
    signal = make_signal("lt1", "-0.6")
    strategy = make_strategy("lt1", signal)
    scheduler, _ = make_scheduler({"lt1": strategy}, {})
    bias = await scheduler._compute_bias()
    assert bias == "bearish"


@pytest.mark.asyncio
async def test_compute_bias_neutral_when_no_long_term_signals():
    strategy = make_strategy("lt1", None)
    scheduler, _ = make_scheduler({"lt1": strategy}, {})
    bias = await scheduler._compute_bias()
    assert bias == "neutral"


def test_apply_bias_filter_blocks_sell_in_bullish_bias():
    scheduler, _ = make_scheduler({}, {})
    sell_signal = make_signal("s1", "-0.5")
    result = scheduler._apply_bias_filter(sell_signal, "bullish")
    assert result is None


def test_apply_bias_filter_allows_buy_in_bullish_bias():
    scheduler, _ = make_scheduler({}, {})
    buy_signal = make_signal("s1", "0.7")
    result = scheduler._apply_bias_filter(buy_signal, "bullish")
    assert result is buy_signal


def test_apply_bias_filter_blocks_buy_in_bearish_bias():
    scheduler, _ = make_scheduler({}, {})
    buy_signal = make_signal("s1", "0.5")
    result = scheduler._apply_bias_filter(buy_signal, "bearish")
    assert result is None


def test_apply_bias_filter_allows_sell_in_bearish_bias():
    scheduler, _ = make_scheduler({}, {})
    sell_signal = make_signal("s1", "-0.7")
    result = scheduler._apply_bias_filter(sell_signal, "bearish")
    assert result is sell_signal


def test_apply_bias_filter_allows_all_in_neutral_bias():
    scheduler, _ = make_scheduler({}, {})
    buy_signal = make_signal("s1", "0.5")
    sell_signal = make_signal("s2", "-0.5")
    assert scheduler._apply_bias_filter(buy_signal, "neutral") is buy_signal
    assert scheduler._apply_bias_filter(sell_signal, "neutral") is sell_signal


@pytest.mark.asyncio
async def test_run_once_submits_intraday_signal_when_bias_allows():
    lt_signal = make_signal("lt1", "0.8")
    lt_strategy = make_strategy("lt1", lt_signal)

    intraday_signal = make_signal("id1", "0.6")
    id_strategy = make_strategy("id1", intraday_signal)
    id_strategy.bar_size = "15 mins"

    scheduler, mock_manager = make_scheduler(
        {"lt1": lt_strategy},
        {"id1": id_strategy},
    )
    await scheduler._run_once()
    mock_manager.process_signal.assert_called_once_with(intraday_signal)


@pytest.mark.asyncio
async def test_run_once_does_not_submit_intraday_signal_when_bias_blocks():
    lt_signal = make_signal("lt1", "0.8")
    lt_strategy = make_strategy("lt1", lt_signal)

    intraday_signal = make_signal("id1", "-0.6")
    id_strategy = make_strategy("id1", intraday_signal)
    id_strategy.bar_size = "15 mins"

    scheduler, mock_manager = make_scheduler(
        {"lt1": lt_strategy},
        {"id1": id_strategy},
    )
    await scheduler._run_once()
    mock_manager.process_signal.assert_not_called()


@pytest.mark.asyncio
async def test_run_once_continues_after_risk_violation_in_process_signal():
    """_run_once must not abort when order_manager.process_signal raises RiskViolationError."""
    from polara.risk_guard.exceptions import RiskViolationError

    lt_signal = make_signal("lt1", "0.8")
    lt_strategy = make_strategy("lt1", lt_signal)

    intraday_signal1 = make_signal("id1", "0.6")
    id_strategy1 = make_strategy("id1", intraday_signal1)
    id_strategy1.bar_size = "15 mins"

    intraday_signal2 = make_signal("id2", "0.5")
    id_strategy2 = make_strategy("id2", intraday_signal2)
    id_strategy2.bar_size = "15 mins"

    mock_svc = AsyncMock()
    mock_svc.get_bars = AsyncMock(return_value=[make_bar()])
    registry = MagicMock()
    all_strategies = {
        "lt1": lt_strategy,
        "id1": id_strategy1,
        "id2": id_strategy2,
    }
    registry.get = MagicMock(side_effect=lambda sid: all_strategies[sid])
    mock_manager = AsyncMock()
    # First call raises, second should still be called
    mock_manager.process_signal = AsyncMock(
        side_effect=[RiskViolationError("test"), None]
    )

    scheduler = ConfluentScheduler(
        market_data_svc=mock_svc,
        registry=registry,
        order_manager=mock_manager,
        long_term_ids=["lt1"],
        intraday_ids=["id1", "id2"],
        min_bias_strength=Decimal("0"),
    )
    # Should not raise
    await scheduler._run_once()
    # Both strategies were attempted
    assert mock_manager.process_signal.call_count == 2


@pytest.mark.asyncio
async def test_compute_bias_continues_when_long_term_strategy_raises():
    """_compute_bias must catch exceptions from long-term strategies and continue."""
    lt_strategy_ok = make_strategy("lt1", make_signal("lt1", "0.8"))
    lt_strategy_bad = make_strategy("lt2", None)

    mock_svc = AsyncMock()
    # First call (lt2) raises, second call (lt1) returns bars normally
    mock_svc.get_bars = AsyncMock(side_effect=[Exception("boom"), [make_bar()]])

    registry = MagicMock()
    all_strategies = {"lt1": lt_strategy_ok, "lt2": lt_strategy_bad}
    registry.get = MagicMock(side_effect=lambda sid: all_strategies[sid])

    mock_manager = AsyncMock()
    scheduler = ConfluentScheduler(
        market_data_svc=mock_svc,
        registry=registry,
        order_manager=mock_manager,
        long_term_ids=["lt2", "lt1"],
        intraday_ids=[],
        min_bias_strength=Decimal("0"),
    )
    # Should not propagate the exception — returns bias based on remaining signals
    bias = await scheduler._compute_bias()
    assert bias in {"bullish", "bearish", "neutral"}
