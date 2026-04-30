"""Tests for MACrossoverStrategy."""
from datetime import UTC, datetime
from decimal import Decimal

from polara.research_engine.strategies.ma_crossover import MACrossoverStrategy
from polara.schemas.market import Bar


def make_bar(close: Decimal, i: int = 0) -> Bar:
    return Bar(
        symbol="AAPL",
        timestamp=datetime(2026, 1, 1, 10, i % 60, i // 60, tzinfo=UTC),
        open=close,
        high=close + Decimal("1"),
        low=close - Decimal("1"),
        close=close,
        volume=1000,
    )


def make_bars(closes: list[Decimal]) -> list[Bar]:
    return [make_bar(c, i) for i, c in enumerate(closes)]


def make_strategy(**kwargs) -> MACrossoverStrategy:
    defaults = dict(
        strategy_id="mac-test",
        symbol="AAPL",
        fast_period=5,
        slow_period=20,
        quantity=Decimal("1"),
        bar_size="5 mins",
    )
    defaults.update(kwargs)
    return MACrossoverStrategy(**defaults)


# ── bars_needed ───────────────────────────────────────────────────────────────

def test_bars_needed_default():
    strategy = make_strategy(slow_period=20)
    assert strategy.bars_needed == 21


def test_bars_needed_custom():
    strategy = make_strategy(slow_period=50)
    assert strategy.bars_needed == 51


# ── insufficient bars → None ─────────────────────────────────────────────────

def test_no_signal_insufficient_bars():
    strategy = make_strategy(slow_period=20)
    bars = make_bars([Decimal("100")] * 20)
    assert strategy.on_bars(bars) is None


# ── buy signal ───────────────────────────────────────────────────────────────

def test_buy_signal_fast_crosses_above_slow():
    """Flat then a sustained spike pushes fast MA above slow MA."""
    strategy = make_strategy(fast_period=3, slow_period=6)
    # 7 flat bars then a sharp rise — fast MA crosses above slow MA
    flat = [Decimal("100")] * 7
    spike = [Decimal("200")]
    bars = make_bars(flat + spike)
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.strength == Decimal("1")
    assert signal.symbol == "AAPL"


# ── sell signal ──────────────────────────────────────────────────────────────

def test_sell_signal_fast_crosses_below_slow():
    """Flat then a sharp drop pushes fast MA below slow MA."""
    strategy = make_strategy(fast_period=3, slow_period=6)
    flat = [Decimal("100")] * 7
    drop = [Decimal("10")]
    bars = make_bars(flat + drop)
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.strength == Decimal("-1")


# ── no signal ────────────────────────────────────────────────────────────────

def test_no_signal_flat_series():
    """Constant prices: no crossover → None."""
    strategy = make_strategy(fast_period=3, slow_period=6)
    bars = make_bars([Decimal("100")] * 30)
    assert strategy.on_bars(bars) is None


# ── signal metadata ───────────────────────────────────────────────────────────

def test_signal_utc_timestamp():
    strategy = make_strategy(fast_period=3, slow_period=6)
    bars = make_bars([Decimal("100")] * 7 + [Decimal("200")])
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.generated_at.tzinfo is not None


# ── PARAM_GRID ────────────────────────────────────────────────────────────────

def test_param_grid_present():
    strategy = make_strategy()
    assert strategy.PARAM_GRID is not None
    assert "fast_period" in strategy.PARAM_GRID
    assert "slow_period" in strategy.PARAM_GRID


def test_param_grid_types():
    strategy = make_strategy()
    for v in strategy.PARAM_GRID["fast_period"]:
        assert isinstance(v, int)
    for v in strategy.PARAM_GRID["slow_period"]:
        assert isinstance(v, int)
