"""Tests for MomentumStrategy (Rate-of-Change)."""
from datetime import UTC, datetime
from decimal import Decimal

from polara.research_engine.strategies.momentum import MomentumStrategy, _roc
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


def make_strategy(**kwargs) -> MomentumStrategy:
    defaults = dict(
        strategy_id="mom-test",
        symbol="AAPL",
        period=14,
        threshold=Decimal("2"),
        quantity=Decimal("1"),
        bar_size="1 hour",
    )
    defaults.update(kwargs)
    return MomentumStrategy(**defaults)


# ── bars_needed ───────────────────────────────────────────────────────────────

def test_bars_needed_default():
    assert make_strategy().bars_needed == 14 + 2


def test_bars_needed_custom():
    assert make_strategy(period=5).bars_needed == 5 + 2


# ── _roc helper ───────────────────────────────────────────────────────────────

def test_roc_zero_for_constant():
    """Constant price → ROC = 0%."""
    closes = [Decimal("100")] * 20
    assert _roc(closes, 14) == Decimal("0")


def test_roc_positive_on_gain():
    """Price rose 10% over period → ROC = 10."""
    closes = [Decimal("100")] * 14 + [Decimal("110")]
    result = _roc(closes, 14)
    assert result == Decimal("10")


def test_roc_negative_on_loss():
    """Price fell 10% over period → ROC = -10."""
    closes = [Decimal("100")] * 14 + [Decimal("90")]
    result = _roc(closes, 14)
    assert result == Decimal("-10")


def test_roc_zero_prior():
    """Prior price = 0 → ROC = 0 (guard against division by zero)."""
    closes = [Decimal("0")] * 14 + [Decimal("100")]
    assert _roc(closes, 14) == Decimal("0")


# ── insufficient bars → None ─────────────────────────────────────────────────

def test_no_signal_insufficient_bars():
    strategy = make_strategy()
    bars = make_bars([Decimal("100")] * (strategy.bars_needed - 1))
    assert strategy.on_bars(bars) is None


# ── buy signal: ROC crosses above +threshold ─────────────────────────────────

def test_buy_signal_roc_crosses_above_threshold():
    """ROC crosses from below +2% to above +2% → buy signal."""
    strategy = make_strategy(period=5, threshold=Decimal("2"))
    # 6 bars at 100 (ROC ~0%) then price jumps to 110 (ROC = 10% > 2%)
    # Previous ROC was 0 (≤ 2), current ROC is 10 (> 2) → crossover
    closes = [Decimal("100")] * 7 + [Decimal("110")]
    bars = make_bars(closes)
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.strength == Decimal("1")


# ── sell signal: ROC crosses below −threshold ─────────────────────────────────

def test_sell_signal_roc_crosses_below_negative_threshold():
    """ROC crosses from above −2% to below −2% → sell signal."""
    strategy = make_strategy(period=5, threshold=Decimal("2"))
    # 6 bars at 100 (ROC ~0%) then price drops to 90 (ROC = -10% < -2%)
    closes = [Decimal("100")] * 7 + [Decimal("90")]
    bars = make_bars(closes)
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.strength == Decimal("-1")


# ── no signal when ROC doesn't cross ─────────────────────────────────────────

def test_no_signal_flat_roc():
    """Constant prices → ROC stays at 0 → no crossover → None."""
    strategy = make_strategy(period=5, threshold=Decimal("2"))
    bars = make_bars([Decimal("100")] * 30)
    assert strategy.on_bars(bars) is None


# ── signal metadata ───────────────────────────────────────────────────────────

def test_signal_utc_timestamp():
    strategy = make_strategy(period=5, threshold=Decimal("2"))
    bars = make_bars([Decimal("100")] * 7 + [Decimal("110")])
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.generated_at.tzinfo is not None


def test_take_profit_propagates():
    strategy = make_strategy(period=5, threshold=Decimal("2"), take_profit_pct=Decimal("6"))
    bars = make_bars([Decimal("100")] * 7 + [Decimal("110")])
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.take_profit_pct == Decimal("6")
