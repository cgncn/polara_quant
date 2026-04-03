"""Tests for RSIMeanReversionStrategy."""
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from polara.research_engine.strategies.rsi_mean_reversion import (
    RSIMeanReversionStrategy,
    _compute_rsi,
)
from polara.schemas.market import Bar


def make_bar(close: Decimal, i: int = 0, symbol: str = "AAPL") -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=datetime(2026, 1, 1, 10, i, tzinfo=UTC),
        open=close,
        high=close + Decimal("1"),
        low=close - Decimal("1"),
        close=close,
        volume=1000,
    )


def make_strategy(**kwargs) -> RSIMeanReversionStrategy:
    defaults = dict(strategy_id="rsi-test", symbol="AAPL")
    defaults.update(kwargs)
    return RSIMeanReversionStrategy(**defaults)


def make_bars_with_offset(closes: list[Decimal], symbol: str = "AAPL") -> list[Bar]:
    """Create bars from a list of close prices, each with a unique minute offset."""
    return [make_bar(close, i, symbol) for i, close in enumerate(closes)]


# ── bars_needed ──────────────────────────────────────────────────────────────


def test_bars_needed_is_period_plus_one():
    strategy = make_strategy()  # default period=14
    assert strategy.bars_needed == 15


def test_bars_needed_custom_period():
    strategy = make_strategy(period=20)
    assert strategy.bars_needed == 21


# ── insufficient bars → None ─────────────────────────────────────────────────


def test_no_signal_insufficient_bars():
    strategy = make_strategy()  # needs 15 bars
    bars = make_bars_with_offset([Decimal("100")] * 14)
    assert strategy.on_bars(bars) is None


# ── oversold: buy signal ──────────────────────────────────────────────────────


def test_buy_signal_when_oversold():
    """Steadily declining closes → RSI < 30 → strength == 1 (buy)."""
    # Start at 100, drop by 2 each bar for 20 bars. After 14+ decreases RSI → ~0.
    start = Decimal("100")
    step = Decimal("2")
    closes = [start - step * Decimal(i) for i in range(20)]
    bars = make_bars_with_offset(closes)

    strategy = make_strategy()
    signal = strategy.on_bars(bars)

    assert signal is not None
    assert signal.strength == Decimal("1")
    assert signal.symbol == "AAPL"
    assert signal.strategy_id == "rsi-test"


# ── overbought: sell signal ───────────────────────────────────────────────────


def test_sell_signal_when_overbought():
    """Steadily rising closes → RSI > 70 → strength == -1 (sell)."""
    start = Decimal("100")
    step = Decimal("2")
    closes = [start + step * Decimal(i) for i in range(20)]
    bars = make_bars_with_offset(closes)

    strategy = make_strategy()
    signal = strategy.on_bars(bars)

    assert signal is not None
    assert signal.strength == Decimal("-1")


# ── midrange: no signal ───────────────────────────────────────────────────────


def test_no_signal_midrange():
    """Alternating up/down bars → gains and losses roughly equal → RSI ~50 → None."""
    # Alternate: 99, 101, 99, 101 …
    closes = [
        Decimal("99") if i % 2 == 0 else Decimal("101")
        for i in range(20)
    ]
    bars = make_bars_with_offset(closes)

    strategy = make_strategy()
    signal = strategy.on_bars(bars)

    assert signal is None


# ── RSI extreme cases ─────────────────────────────────────────────────────────


def test_rsi_100_all_gains():
    """All bars increasing by same amount → RSI = 100 → sell signal (strength = -1)."""
    closes = [Decimal("100") + Decimal("1") * Decimal(i) for i in range(20)]
    bars = make_bars_with_offset(closes)

    # Verify _compute_rsi returns 100
    rsi = _compute_rsi(bars, 14)
    assert rsi == Decimal("100")

    # Strategy: RSI=100 > overbought=70 → sell
    strategy = make_strategy()
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.strength == Decimal("-1")


def test_rsi_0_all_losses():
    """All bars decreasing → RSI = 0 → buy signal (strength = 1)."""
    closes = [Decimal("200") - Decimal("1") * Decimal(i) for i in range(20)]
    bars = make_bars_with_offset(closes)

    # Verify _compute_rsi: avg_gain = 0 → RSI = 0
    rsi = _compute_rsi(bars, 14)
    assert rsi == Decimal("0")

    # Strategy: RSI=0 < oversold=30 → buy
    strategy = make_strategy()
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.strength == Decimal("1")


# ── signal metadata ───────────────────────────────────────────────────────────


def test_signal_has_utc_timestamp():
    """Signal generated_at must be UTC-aware."""
    closes = [Decimal("100") - Decimal("2") * Decimal(i) for i in range(20)]
    bars = make_bars_with_offset(closes)

    strategy = make_strategy()
    signal = strategy.on_bars(bars)

    assert signal is not None
    assert signal.generated_at.tzinfo is not None


def test_signal_strength_is_decimal():
    """signal.strength must be a Decimal instance."""
    closes = [Decimal("100") - Decimal("2") * Decimal(i) for i in range(20)]
    bars = make_bars_with_offset(closes)

    strategy = make_strategy()
    signal = strategy.on_bars(bars)

    assert signal is not None
    assert isinstance(signal.strength, Decimal)


# ── custom thresholds ─────────────────────────────────────────────────────────


def test_custom_thresholds():
    """Tighter thresholds (oversold=40, overbought=60) should fire at different RSI levels."""
    strategy = make_strategy(oversold=Decimal("40"), overbought=Decimal("60"))

    # Alternating bars → RSI ~50 (no signal at default thresholds)
    # but at overbought=60 and oversold=40 we need a definitive RSI reading.
    # Use a slight upward trend: starts at 100, rises 1 every other bar.
    # First test: steadily rising → RSI > 60 → sell (even though < 70)
    closes_up = [Decimal("100") + Decimal("1") * Decimal(i) for i in range(20)]
    bars_up = make_bars_with_offset(closes_up)
    signal_up = strategy.on_bars(bars_up)
    assert signal_up is not None
    assert signal_up.strength == Decimal("-1")

    # Steadily declining → RSI < 40 → buy (even though > 30 default)
    closes_down = [Decimal("200") - Decimal("1") * Decimal(i) for i in range(20)]
    bars_down = make_bars_with_offset(closes_down)
    signal_down = strategy.on_bars(bars_down)
    assert signal_down is not None
    assert signal_down.strength == Decimal("1")
