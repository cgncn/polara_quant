"""Tests for SupertrendStrategy."""
from datetime import UTC, datetime
from decimal import Decimal

from polara.research_engine.strategies.supertrend import SupertrendStrategy
from polara.schemas.market import Bar


def make_bar(
    close: Decimal,
    high: Decimal | None = None,
    low: Decimal | None = None,
    i: int = 0,
) -> Bar:
    h = high if high is not None else close + Decimal("1")
    l = low if low is not None else close - Decimal("1")
    return Bar(
        symbol="AAPL",
        timestamp=datetime(2026, 1, 2, 10, i % 60, i // 60, tzinfo=UTC),
        open=close,
        high=h,
        low=l,
        close=close,
        volume=1000,
    )


def make_flat_bars(close: Decimal, count: int) -> list[Bar]:
    """Tiny-range flat bars to anchor ATR at a low value."""
    return [
        Bar(
            symbol="AAPL",
            timestamp=datetime(2026, 1, 2, 10, i % 60, i // 60, tzinfo=UTC),
            open=close,
            high=close + Decimal("0.5"),
            low=close - Decimal("0.5"),
            close=close,
            volume=1000,
        )
        for i in range(count)
    ]


def make_bearish_bar(i: int = 0) -> Bar:
    """Bar that closed at its low with a large upper wick — signals downtrend."""
    return Bar(
        symbol="AAPL",
        timestamp=datetime(2026, 1, 2, 10, i % 60, i // 60, tzinfo=UTC),
        open=Decimal("107"),
        high=Decimal("120"),
        low=Decimal("95"),
        close=Decimal("95"),
        volume=1000,
    )


def make_bullish_bar(i: int = 0) -> Bar:
    """Bar that closed at its high with a large lower wick — signals uptrend."""
    return Bar(
        symbol="AAPL",
        timestamp=datetime(2026, 1, 2, 10, i % 60, i // 60, tzinfo=UTC),
        open=Decimal("107"),
        high=Decimal("120"),
        low=Decimal("95"),
        close=Decimal("120"),
        volume=1000,
    )


def make_strategy(**kwargs) -> SupertrendStrategy:
    defaults = dict(
        strategy_id="st-test",
        symbol="AAPL",
        bar_size="5 mins",
        atr_period=5,
        multiplier=Decimal("2.0"),
    )
    defaults.update(kwargs)
    return SupertrendStrategy(**defaults)


# ── bars_needed ───────────────────────────────────────────────────────────────

def test_bars_needed_default():
    strategy = make_strategy(atr_period=10)
    assert strategy.bars_needed == 12


def test_bars_needed_custom():
    strategy = make_strategy(atr_period=7)
    assert strategy.bars_needed == 9


# ── insufficient bars → None ─────────────────────────────────────────────────

def test_no_signal_insufficient_bars():
    strategy = make_strategy()  # atr_period=5 → needs 7 bars
    bars = make_flat_bars(Decimal("100"), 6)
    assert strategy.on_bars(bars) is None


# ── ATR = 0 (flat candles) → None ────────────────────────────────────────────

def test_no_signal_when_atr_zero():
    """Constant prices with zero range → ATR=0 → no signal."""
    strategy = make_strategy()
    bars = [
        Bar(
            symbol="AAPL",
            timestamp=datetime(2026, 1, 2, 10, i, 0, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=1000,
        )
        for i in range(10)
    ]
    assert strategy.on_bars(bars) is None


# ── buy signal: downtrend → uptrend flip ─────────────────────────────────────

def test_buy_signal_on_uptrend_flip():
    """
    Uses large-wick bars: prev closed at its low (bearish → prev_close < lower_band),
    curr closes at its high (bullish → curr_close > upper_band). Direction flips.
    The flat bars keep ATR small so the large wick bars sit outside the bands.
    """
    strategy = make_strategy(atr_period=5, multiplier=Decimal("1.0"))
    flat = make_flat_bars(Decimal("100"), 5)
    prev_bar = make_bearish_bar(i=5)  # close=95, below lower band (~97)
    curr_bar = make_bullish_bar(i=6)  # close=120, above upper band (~117)
    bars = flat + [prev_bar, curr_bar]
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.strength == Decimal("1")
    assert signal.symbol == "AAPL"


# ── sell signal: uptrend → downtrend flip ────────────────────────────────────

def test_sell_signal_on_downtrend_flip():
    """
    prev closed at its high (bullish → prev_close > upper_band),
    curr closed at its low (bearish → curr_close < lower_band). Direction flips.
    """
    strategy = make_strategy(atr_period=5, multiplier=Decimal("1.0"))
    flat = make_flat_bars(Decimal("100"), 5)
    prev_bar = make_bullish_bar(i=5)  # close=120, uptrend
    curr_bar = make_bearish_bar(i=6)  # close=95, downtrend
    bars = flat + [prev_bar, curr_bar]
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.strength == Decimal("-1")


# ── no signal without direction flip ─────────────────────────────────────────

def test_no_signal_when_no_flip():
    """Both prev and curr in the same zone → no flip → None."""
    strategy = make_strategy(atr_period=5, multiplier=Decimal("1.0"))
    flat = make_flat_bars(Decimal("100"), 5)
    prev_bar = make_bullish_bar(i=5)
    curr_bar = make_bullish_bar(i=6)  # same zone, no flip
    bars = flat + [prev_bar, curr_bar]
    assert strategy.on_bars(bars) is None


# ── PARAM_GRID ────────────────────────────────────────────────────────────────

def test_param_grid_present():
    strategy = make_strategy()
    assert strategy.PARAM_GRID is not None
    assert "atr_period" in strategy.PARAM_GRID
    assert "multiplier" in strategy.PARAM_GRID


def test_param_grid_types():
    strategy = make_strategy()
    for v in strategy.PARAM_GRID["atr_period"]:
        assert isinstance(v, int)
    for v in strategy.PARAM_GRID["multiplier"]:
        assert isinstance(v, str)


# ── signal metadata ───────────────────────────────────────────────────────────

def test_signal_utc_timestamp():
    strategy = make_strategy(atr_period=5, multiplier=Decimal("1.0"))
    flat = make_flat_bars(Decimal("100"), 5)
    bars = flat + [make_bearish_bar(i=5), make_bullish_bar(i=6)]
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.generated_at.tzinfo is not None


def test_strength_is_decimal():
    strategy = make_strategy(atr_period=5, multiplier=Decimal("1.0"))
    flat = make_flat_bars(Decimal("100"), 5)
    bars = flat + [make_bearish_bar(i=5), make_bullish_bar(i=6)]
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert isinstance(signal.strength, Decimal)
