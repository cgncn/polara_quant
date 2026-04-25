"""Tests for BollingerBandStrategy."""
from datetime import UTC, datetime
from decimal import Decimal

from polara.research_engine.strategies.bollinger_bands import BollingerBandStrategy, _bollinger
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


def make_strategy(**kwargs) -> BollingerBandStrategy:
    defaults = dict(
        strategy_id="bb-test",
        symbol="AAPL",
        period=20,
        num_std=Decimal("2"),
        quantity=Decimal("1"),
        bar_size="1 hour",
    )
    defaults.update(kwargs)
    return BollingerBandStrategy(**defaults)


# ── bars_needed ───────────────────────────────────────────────────────────────

def test_bars_needed_default():
    assert make_strategy().bars_needed == 21


def test_bars_needed_custom_period():
    assert make_strategy(period=10).bars_needed == 11


# ── _bollinger helper ─────────────────────────────────────────────────────────

def test_bollinger_constant_series():
    """Constant prices → std = 0 → all three bands equal the constant."""
    closes = [Decimal("100")] * 20
    mid, upper, lower = _bollinger(closes, 20, Decimal("2"))
    assert mid == Decimal("100")
    assert upper == Decimal("100")
    assert lower == Decimal("100")


def test_bollinger_bands_symmetric():
    """Upper and lower bands should be equidistant from the middle."""
    closes = [Decimal(str(i)) for i in range(20, 40)]
    mid, upper, lower = _bollinger(closes, 20, Decimal("2"))
    assert upper - mid == mid - lower


# ── insufficient bars → None ─────────────────────────────────────────────────

def test_no_signal_insufficient_bars():
    strategy = make_strategy()
    bars = make_bars([Decimal("100")] * 20)
    assert strategy.on_bars(bars) is None


# ── buy signal: close crosses below lower band ────────────────────────────────

def test_buy_signal_crosses_below_lower_band():
    """Stable prices then a sharp drop pushes last close below the lower band."""
    strategy = make_strategy(period=5, num_std=Decimal("1"))
    # 6 stable bars at 100, then one very low close
    stable = [Decimal("100")] * 6
    drop = [Decimal("50")]  # way below lower band
    bars = make_bars(stable + drop)
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.strength == Decimal("1")


# ── sell signal: close crosses above upper band ───────────────────────────────

def test_sell_signal_crosses_above_upper_band():
    """Stable prices then a sharp spike pushes last close above the upper band."""
    strategy = make_strategy(period=5, num_std=Decimal("1"))
    stable = [Decimal("100")] * 6
    spike = [Decimal("200")]  # way above upper band
    bars = make_bars(stable + spike)
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.strength == Decimal("-1")


# ── no signal inside the bands ────────────────────────────────────────────────

def test_no_signal_inside_bands():
    """Close remains inside bands → no signal."""
    strategy = make_strategy(period=5, num_std=Decimal("2"))
    closes = [Decimal("100")] * 30
    bars = make_bars(closes)
    assert strategy.on_bars(bars) is None


# ── signal metadata ───────────────────────────────────────────────────────────

def test_signal_utc_timestamp():
    strategy = make_strategy(period=5, num_std=Decimal("1"))
    bars = make_bars([Decimal("100")] * 6 + [Decimal("50")])
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.generated_at.tzinfo is not None


def test_stop_loss_propagates():
    strategy = make_strategy(period=5, num_std=Decimal("1"), stop_loss_pct=Decimal("3"))
    bars = make_bars([Decimal("100")] * 6 + [Decimal("50")])
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.stop_loss_pct == Decimal("3")
