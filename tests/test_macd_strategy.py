"""Tests for MACDStrategy."""
from datetime import UTC, datetime
from decimal import Decimal

from polara.research_engine.strategies.macd import MACDStrategy, _ema
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


def make_strategy(**kwargs) -> MACDStrategy:
    defaults = dict(
        strategy_id="macd-test",
        symbol="AAPL",
        fast_period=12,
        slow_period=26,
        signal_period=9,
        quantity=Decimal("1"),
        bar_size="1 hour",
    )
    defaults.update(kwargs)
    return MACDStrategy(**defaults)


# ── bars_needed ───────────────────────────────────────────────────────────────

def test_bars_needed_default():
    strategy = make_strategy()
    assert strategy.bars_needed == 26 + 9 + 1


def test_bars_needed_custom():
    strategy = make_strategy(fast_period=5, slow_period=10, signal_period=3)
    assert strategy.bars_needed == 10 + 3 + 1


# ── _ema helper ───────────────────────────────────────────────────────────────

def test_ema_constant_series():
    """EMA of a constant series should equal the constant."""
    values = [Decimal("50")] * 20
    result = _ema(values, 10)
    assert len(result) == 20
    # All values should equal 50
    for v in result:
        assert abs(v - Decimal("50")) < Decimal("0.001")


def test_ema_empty_when_too_few_values():
    result = _ema([Decimal("100")] * 3, period=10)
    assert result == []


# ── insufficient bars → None ─────────────────────────────────────────────────

def test_no_signal_insufficient_bars():
    strategy = make_strategy()
    bars = make_bars([Decimal("100")] * (strategy.bars_needed - 1))
    assert strategy.on_bars(bars) is None


# ── buy signal: MACD crosses above signal ─────────────────────────────────────

def test_buy_signal_macd_crosses_above():
    """Flat prices then ONE spike at the last bar drives fast EMA above slow EMA.

    At the prev bar: MACD = 0 = signal (both flat).
    At the last bar: fast EMA rises faster than slow EMA → MACD crosses above signal.
    """
    strategy = make_strategy(fast_period=3, slow_period=6, signal_period=3)
    # Many flat bars so all EMAs converge to 100, then one spike.
    flat = [Decimal("100")] * 30
    spike = [Decimal("200")]
    bars = make_bars(flat + spike)
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.strength == Decimal("1")
    assert signal.symbol == "AAPL"


# ── sell signal: MACD crosses below signal ────────────────────────────────────

def test_sell_signal_macd_crosses_below():
    """Flat prices then ONE sharp drop at the last bar drives fast EMA below slow EMA."""
    strategy = make_strategy(fast_period=3, slow_period=6, signal_period=3)
    flat = [Decimal("100")] * 30
    drop = [Decimal("5")]  # sharp drop; must stay > 1 so low (close-1) > 0
    bars = make_bars(flat + drop)
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.strength == Decimal("-1")


# ── no signal on flat series ──────────────────────────────────────────────────

def test_no_signal_flat_series():
    """Constant price → MACD line = 0, signal line = 0, no crossover."""
    strategy = make_strategy(fast_period=3, slow_period=6, signal_period=3)
    bars = make_bars([Decimal("100")] * 50)
    assert strategy.on_bars(bars) is None


# ── signal metadata ───────────────────────────────────────────────────────────

def test_signal_has_utc_timestamp():
    strategy = make_strategy(fast_period=3, slow_period=6, signal_period=3)
    bars = make_bars([Decimal("100")] * 30 + [Decimal("200")])
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.generated_at.tzinfo is not None


def test_stop_loss_propagates():
    strategy = make_strategy(
        fast_period=3, slow_period=6, signal_period=3,
        stop_loss_pct=Decimal("4"),
    )
    bars = make_bars([Decimal("100")] * 30 + [Decimal("200")])
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.stop_loss_pct == Decimal("4")


# ── PARAM_GRID ────────────────────────────────────────────────────────────────

def test_param_grid_present():
    strategy = make_strategy()
    assert strategy.PARAM_GRID is not None
    assert set(strategy.PARAM_GRID.keys()) == {"fast_period", "slow_period", "signal_period"}


def test_param_grid_types():
    strategy = make_strategy()
    for key in ("fast_period", "slow_period", "signal_period"):
        for v in strategy.PARAM_GRID[key]:
            assert isinstance(v, int), f"{key} grid values must be int, got {type(v)}"
