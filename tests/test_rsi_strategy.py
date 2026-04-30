"""Tests for RSIMeanReversionStrategy (crossover-based entry logic)."""
from datetime import UTC, datetime
from decimal import Decimal

from polara.research_engine.strategies.rsi_mean_reversion import (
    RSIMeanReversionStrategy,
    _compute_rsi,
)
from polara.schemas.market import Bar


def make_bar(close: Decimal, i: int = 0, symbol: str = "AAPL") -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=datetime(2026, 1, 1, 10, i % 60, i // 60, tzinfo=UTC),
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
    return [make_bar(close, i, symbol) for i, close in enumerate(closes)]


# ── bars_needed ──────────────────────────────────────────────────────────────


def test_bars_needed_is_period_plus_two():
    strategy = make_strategy()  # default period=14
    assert strategy.bars_needed == 16


def test_bars_needed_custom_period():
    strategy = make_strategy(period=20)
    assert strategy.bars_needed == 22


# ── insufficient bars → None ─────────────────────────────────────────────────


def test_no_signal_insufficient_bars():
    strategy = make_strategy()  # needs 16 bars
    bars = make_bars_with_offset([Decimal("100")] * 15)
    assert strategy.on_bars(bars) is None


# ── buy signal: RSI recovers above oversold threshold ────────────────────────


def test_buy_signal_on_recovery_from_oversold():
    """
    Decline to push RSI well below 30, then one large up-bar recovers RSI above 30.
    Strategy should fire a buy signal on the recovery bar.
    """
    strategy = make_strategy()  # period=14, oversold=30

    # 15 declining bars → rsi_prev deeply oversold (< 30)
    declining = [Decimal(str(100 - 2 * i)) for i in range(15)]
    # One big recovery bar — large jump ensures RSI crosses back above 30
    recovery = [declining[-1] + Decimal("40")]
    closes = declining + recovery
    bars = make_bars_with_offset(closes)

    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.strength == Decimal("1")
    assert signal.symbol == "AAPL"
    assert signal.strategy_id == "rsi-test"
    assert signal.reference_price == bars[-1].close


# ── sell signal: RSI pulls back below overbought threshold ───────────────────


def test_sell_signal_on_recovery_from_overbought():
    """
    Rise to push RSI well above 70, then one large down-bar pulls RSI back below 70.
    Strategy should fire a sell signal on the pullback bar.
    """
    strategy = make_strategy()  # period=14, overbought=70

    # 15 rising bars → rsi_prev deeply overbought (> 70)
    rising = [Decimal(str(100 + 2 * i)) for i in range(15)]
    # One big down bar — large drop ensures RSI crosses back below 70
    pullback = [rising[-1] - Decimal("40")]
    closes = rising + pullback
    bars = make_bars_with_offset(closes)

    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.strength == Decimal("-1")
    assert signal.reference_price == bars[-1].close


# ── no signal while still in extreme zone ────────────────────────────────────


def test_no_signal_while_still_oversold():
    """Purely declining series: RSI stays below 30 every bar — no crossover, no signal."""
    strategy = make_strategy()
    closes = [Decimal(str(200 - 2 * i)) for i in range(16)]
    bars = make_bars_with_offset(closes)
    assert strategy.on_bars(bars) is None


def test_no_signal_while_still_overbought():
    """Purely rising series: RSI stays above 70 every bar — no crossover, no signal."""
    strategy = make_strategy()
    closes = [Decimal(str(100 + 2 * i)) for i in range(16)]
    bars = make_bars_with_offset(closes)
    assert strategy.on_bars(bars) is None


# ── midrange: no signal ───────────────────────────────────────────────────────


def test_no_signal_midrange():
    """Alternating bars → RSI ~50 → never crosses threshold → None."""
    closes = [
        Decimal("99") if i % 2 == 0 else Decimal("101")
        for i in range(20)
    ]
    bars = make_bars_with_offset(closes)
    assert make_strategy().on_bars(bars) is None


# ── RSI helper function tests ─────────────────────────────────────────────────


def test_rsi_100_all_gains():
    """All bars increasing → RSI = 100."""
    closes = [Decimal("100") + Decimal("1") * Decimal(i) for i in range(20)]
    bars = make_bars_with_offset(closes)
    rsi = _compute_rsi(bars, 14)
    assert rsi == Decimal("100")


def test_rsi_0_all_losses():
    """All bars decreasing → RSI = 0."""
    closes = [Decimal("200") - Decimal("1") * Decimal(i) for i in range(20)]
    bars = make_bars_with_offset(closes)
    rsi = _compute_rsi(bars, 14)
    assert rsi == Decimal("0")


# ── crossover fires exactly once ──────────────────────────────────────────────


def test_buy_crossover_fires_on_recovery_bar():
    """Signal fires on the bar where RSI crosses back above oversold, not before."""
    strategy = make_strategy()

    # Build the series up to the bar before recovery — should be None
    declining = [Decimal(str(100 - 2 * i)) for i in range(15)]
    bars_before_recovery = make_bars_with_offset(declining)
    assert strategy.on_bars(bars_before_recovery) is None

    # Add recovery bar — now crossover fires
    recovery_close = declining[-1] + Decimal("40")
    bars_with_recovery = make_bars_with_offset(declining + [recovery_close])
    signal = strategy.on_bars(bars_with_recovery)
    assert signal is not None
    assert signal.strength == Decimal("1")


# ── PARAM_GRID ────────────────────────────────────────────────────────────────


def test_param_grid_present():
    strategy = make_strategy()
    assert strategy.PARAM_GRID is not None
    assert "period" in strategy.PARAM_GRID
    assert "oversold" in strategy.PARAM_GRID
    assert "overbought" in strategy.PARAM_GRID


def test_param_grid_types():
    strategy = make_strategy()
    for v in strategy.PARAM_GRID["period"]:
        assert isinstance(v, int)
    for v in strategy.PARAM_GRID["oversold"]:
        assert isinstance(v, str)
    for v in strategy.PARAM_GRID["overbought"]:
        assert isinstance(v, str)


# ── signal metadata ───────────────────────────────────────────────────────────


def test_signal_has_utc_timestamp():
    strategy = make_strategy()
    declining = [Decimal(str(100 - 2 * i)) for i in range(15)]
    recovery = [declining[-1] + Decimal("40")]
    bars = make_bars_with_offset(declining + recovery)
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.generated_at.tzinfo is not None


def test_signal_strength_is_decimal():
    strategy = make_strategy()
    declining = [Decimal(str(100 - 2 * i)) for i in range(15)]
    recovery = [declining[-1] + Decimal("40")]
    bars = make_bars_with_offset(declining + recovery)
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert isinstance(signal.strength, Decimal)


# ── stop/take-profit propagation ──────────────────────────────────────────────


def _make_oversold_recovery_bars() -> list[Bar]:
    declining = [Decimal(str(100 - 2 * i)) for i in range(15)]
    recovery = [declining[-1] + Decimal("40")]
    return make_bars_with_offset(declining + recovery)


def test_rsi_signal_includes_stop_loss_pct():
    strategy = make_strategy(stop_loss_pct=Decimal("5"))
    signal = strategy.on_bars(_make_oversold_recovery_bars())
    assert signal is not None
    assert signal.stop_loss_pct == Decimal("5")


def test_rsi_signal_includes_take_profit_pct():
    strategy = make_strategy(take_profit_pct=Decimal("10"))
    signal = strategy.on_bars(_make_oversold_recovery_bars())
    assert signal is not None
    assert signal.take_profit_pct == Decimal("10")


def test_rsi_signal_stop_loss_none_when_not_set():
    strategy = make_strategy()
    signal = strategy.on_bars(_make_oversold_recovery_bars())
    assert signal is not None
    assert signal.stop_loss_pct is None
