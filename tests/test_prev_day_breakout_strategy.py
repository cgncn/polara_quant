"""Tests for PrevDayBreakoutStrategy."""
from datetime import UTC, datetime
from decimal import Decimal

from polara.research_engine.strategies.prev_day_breakout import PrevDayBreakoutStrategy
from polara.schemas.market import Bar


def make_bar(
    price: Decimal,
    ts: datetime,
    volume: int = 1000,
) -> Bar:
    return Bar(
        symbol="AAPL",
        timestamp=ts,
        open=price,
        high=price + Decimal("0.05"),
        low=price - Decimal("0.05"),
        close=price,
        volume=volume,
    )


def make_strategy(**kwargs) -> PrevDayBreakoutStrategy:
    defaults = dict(
        strategy_id="pdb-test",
        symbol="AAPL",
        bar_size="5 mins",
    )
    defaults.update(kwargs)
    return PrevDayBreakoutStrategy(**defaults)


# NYSE session hours for reference dates (UTC):
# 2024-03-04 open = 14:30 UTC, close = 21:00 UTC
# 2024-03-05 open = 14:30 UTC, close = 21:00 UTC


def _yesterday_bars(high: Decimal, low: Decimal, volume: int = 1000) -> list[Bar]:
    """Session bars for 2024-03-04 (yesterday) with specified high and low."""
    # Use a price at midpoint, then override high/low via direct Bar construction
    mid = (high + low) / Decimal("2")
    times = [
        datetime(2024, 3, 4, 15, 0, tzinfo=UTC),
        datetime(2024, 3, 4, 15, 5, tzinfo=UTC),
        datetime(2024, 3, 4, 15, 10, tzinfo=UTC),
        datetime(2024, 3, 4, 15, 15, tzinfo=UTC),
    ]
    # Build bars with explicit high/low to control prev_high / prev_low
    bars = []
    for t in times:
        bars.append(Bar(
            symbol="AAPL",
            timestamp=t,
            open=mid,
            high=high,
            low=low,
            close=mid,
            volume=volume,
        ))
    return bars


def _today_bar(close: Decimal, volume: int = 1000) -> Bar:
    """First bar of 2024-03-05 session at NYSE open."""
    return Bar(
        symbol="AAPL",
        timestamp=datetime(2024, 3, 5, 14, 30, tzinfo=UTC),
        open=close,
        high=close + Decimal("0.05"),
        low=close - Decimal("0.05"),
        close=close,
        volume=volume,
    )


def _pad_to_40(bars: list[Bar]) -> list[Bar]:
    """Prepend pre-session filler bars to reach 40 total bars."""
    needed = 40 - len(bars)
    filler = [
        make_bar(Decimal("99"), datetime(2024, 3, 3, 9, i, tzinfo=UTC))
        for i in range(needed)
    ]
    return filler + bars


def _build_bars(
    prev_high: Decimal,
    prev_low: Decimal,
    today_close: Decimal,
    prev_volume: int = 1000,
    today_volume: int = 1000,
) -> list[Bar]:
    prev_bars = _yesterday_bars(prev_high, prev_low, volume=prev_volume)
    today = _today_bar(today_close, volume=today_volume)
    return _pad_to_40(prev_bars + [today])


# ── bars_needed ────────────────────────────────────────────────────────────────

def test_bars_needed():
    assert make_strategy().bars_needed == 40


# ── insufficient bars → None ───────────────────────────────────────────────────

def test_returns_none_fewer_than_40_bars():
    strategy = make_strategy()
    prev_bars = _yesterday_bars(Decimal("105"), Decimal("95"))
    today = _today_bar(Decimal("106"), volume=5000)
    bars = prev_bars + [today]
    assert len(bars) < 40
    assert strategy.on_bars(bars) is None


# ── no today session bars → None ──────────────────────────────────────────────

def test_returns_none_when_no_today_session_bars():
    strategy = make_strategy()
    prev_bars = _yesterday_bars(Decimal("105"), Decimal("95"))
    # bar in pre-market on 2024-03-05 (before 14:30 UTC)
    pre_market_bar = make_bar(Decimal("106"), datetime(2024, 3, 5, 10, 0, tzinfo=UTC), volume=5000)
    bars = _pad_to_40(prev_bars + [pre_market_bar])
    assert strategy.on_bars(bars) is None


# ── no prev session bars → None ───────────────────────────────────────────────

def test_returns_none_when_no_prev_session_bars():
    strategy = make_strategy()
    # Only today bars + pre-session filler (none on prev trading date)
    today = _today_bar(Decimal("106"), volume=5000)
    filler = [
        make_bar(Decimal("99"), datetime(2024, 3, 5, 9, i, tzinfo=UTC))
        for i in range(39)
    ]
    bars = filler + [today]
    assert strategy.on_bars(bars) is None


# ── buy breakout above prev high ──────────────────────────────────────────────

def test_returns_buy_signal_when_close_above_prev_high_with_volume():
    strategy = make_strategy(volume_factor=Decimal("1.5"))
    # prev avg volume = 1000, need today > 1000 * 1.5 = 1500
    bars = _build_bars(
        prev_high=Decimal("105"),
        prev_low=Decimal("95"),
        today_close=Decimal("106"),  # > prev_high
        prev_volume=1000,
        today_volume=2000,
    )
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.strength == Decimal("1")
    assert signal.reference_price == Decimal("106")
    assert signal.stop_loss_pct == Decimal("0.01")


# ── sell breakout below prev low ──────────────────────────────────────────────

def test_returns_sell_signal_when_close_below_prev_low_with_volume():
    strategy = make_strategy(volume_factor=Decimal("1.5"))
    bars = _build_bars(
        prev_high=Decimal("105"),
        prev_low=Decimal("95"),
        today_close=Decimal("94"),  # < prev_low
        prev_volume=1000,
        today_volume=2000,
    )
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.strength == Decimal("-1")
    assert signal.reference_price == Decimal("94")
    assert signal.stop_loss_pct == Decimal("0.01")


# ── volume below threshold → None ────────────────────────────────────────────

def test_returns_none_when_close_above_prev_high_but_volume_below_threshold():
    strategy = make_strategy(volume_factor=Decimal("1.5"))
    # today volume = 1200 < 1000 * 1.5 = 1500
    bars = _build_bars(
        prev_high=Decimal("105"),
        prev_low=Decimal("95"),
        today_close=Decimal("106"),
        prev_volume=1000,
        today_volume=1200,
    )
    assert strategy.on_bars(bars) is None


# ── price between prev_low and prev_high → None ───────────────────────────────

def test_returns_none_when_price_within_prev_range():
    strategy = make_strategy(volume_factor=Decimal("1.5"))
    bars = _build_bars(
        prev_high=Decimal("105"),
        prev_low=Decimal("95"),
        today_close=Decimal("100"),  # within range
        prev_volume=1000,
        today_volume=2000,
    )
    assert strategy.on_bars(bars) is None


# ── zero-volume guard ─────────────────────────────────────────────────────────

def test_returns_none_when_avg_volume_is_zero():
    strategy = make_strategy(volume_factor=Decimal("1.5"))
    bars = _build_bars(
        prev_high=Decimal("105"),
        prev_low=Decimal("95"),
        today_close=Decimal("106"),
        prev_volume=0,
        today_volume=2000,
    )
    assert strategy.on_bars(bars) is None
