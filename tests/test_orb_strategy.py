"""Tests for OpeningRangeBreakoutStrategy.

Uses March 2024 dates (ET = UTC-5), so NYSE open = 14:30 UTC, close = 21:00 UTC.
bar_size="30 mins", opening_bars=2 → opening range covers 14:30–15:30 UTC.
opening_range_end_utc = 15:30 UTC.
"""
from datetime import UTC, datetime
from decimal import Decimal

from polara.research_engine.strategies.opening_range_breakout import (
    OpeningRangeBreakoutStrategy,
)
from polara.schemas.market import Bar


def make_bar(
    symbol: str,
    timestamp_utc: datetime,
    open_: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
    volume: int = 1000,
) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=timestamp_utc,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _dt(hour: int, minute: int = 0) -> datetime:
    """Return a UTC datetime on 2024-03-05 (Tuesday, regular session)."""
    return datetime(2024, 3, 5, hour, minute, tzinfo=UTC)


# Opening range bars: 14:30 and 15:00 UTC
# range_high = max(high of bar1, high of bar2)
# range_low  = min(low of bar1, low of bar2)
_BAR1 = make_bar("SPY", _dt(14, 30), Decimal("510"), Decimal("512"), Decimal("508"), Decimal("511"))
_BAR2 = make_bar("SPY", _dt(15, 0), Decimal("511"), Decimal("513"), Decimal("509"), Decimal("512"))
# range_high = 513, range_low = 508


def _strategy() -> OpeningRangeBreakoutStrategy:
    return OpeningRangeBreakoutStrategy(
        strategy_id="orb-test",
        symbol="SPY",
        bar_size="30 mins",
        opening_bars=2,
        stop_buffer_pct=Decimal("0.001"),
    )


class TestBarsNeeded:
    def test_bars_needed_is_opening_bars_plus_one(self) -> None:
        s = _strategy()
        assert s.bars_needed == 3


class TestNotEnoughBars:
    def test_returns_none_when_fewer_than_bars_needed(self) -> None:
        s = _strategy()
        assert s.on_bars([_BAR1, _BAR2]) is None

    def test_returns_none_with_empty_bars(self) -> None:
        s = _strategy()
        assert s.on_bars([]) is None

    def test_returns_none_with_single_bar(self) -> None:
        s = _strategy()
        assert s.on_bars([_BAR1]) is None


class TestOpeningRangeNotComplete:
    def test_returns_none_when_opening_range_bars_fewer_than_opening_bars(self) -> None:
        """3 session bars total, but only 1 falls inside the opening range window.

        bar_size="30 mins", opening_bars=2 → or_end = 15:30 UTC.
        Only _BAR1 (14:30) is < or_end; bars at 15:30 and 16:00 are >= or_end.
        So opening_range_bars = [_BAR1] → len 1 < opening_bars 2 → returns None.
        """
        s = _strategy()
        # Only _BAR1 (14:30 UTC) lands inside the OR window (< 15:30 UTC).
        # The remaining two bars are at or after or_end, so they are NOT OR bars.
        bar_at_or_end = make_bar(
            "SPY", _dt(15, 30), Decimal("513"), Decimal("516"), Decimal("512"), Decimal("515")
        )
        bar_after_or_end = make_bar(
            "SPY", _dt(16, 0), Decimal("515"), Decimal("517"), Decimal("514"), Decimal("516")
        )
        # session_bars has 3 entries (>= opening_bars + 1 = 3) but opening_range_bars has only 1 (<2)
        result = s.on_bars([_BAR1, bar_at_or_end, bar_after_or_end])
        assert result is None


class TestBuySignal:
    def test_returns_buy_signal_on_upward_breakout(self) -> None:
        s = _strategy()
        # Close crosses above range_high (513): last close = 515 > 513, prev session close = 512 <= 513
        breakout_bar = make_bar(
            "SPY", _dt(15, 30), Decimal("513"), Decimal("516"), Decimal("512"), Decimal("515")
        )
        result = s.on_bars([_BAR1, _BAR2, breakout_bar])
        assert result is not None
        assert result.strength == Decimal("1")
        assert result.symbol == "SPY"
        assert result.strategy_id == "orb-test"

    def test_buy_signal_reference_price_is_last_close(self) -> None:
        s = _strategy()
        breakout_bar = make_bar(
            "SPY", _dt(15, 30), Decimal("513"), Decimal("516"), Decimal("512"), Decimal("515")
        )
        result = s.on_bars([_BAR1, _BAR2, breakout_bar])
        assert result is not None
        assert result.reference_price == Decimal("515")


class TestSellSignal:
    def test_returns_sell_signal_on_downward_breakout(self) -> None:
        s = _strategy()
        # Close crosses below range_low (508): last close = 506 < 508, prev session close = 512 >= 508
        breakdown_bar = make_bar(
            "SPY", _dt(15, 30), Decimal("508"), Decimal("509"), Decimal("505"), Decimal("506")
        )
        result = s.on_bars([_BAR1, _BAR2, breakdown_bar])
        assert result is not None
        assert result.strength == Decimal("-1")

    def test_sell_signal_reference_price_is_last_close(self) -> None:
        s = _strategy()
        breakdown_bar = make_bar(
            "SPY", _dt(15, 30), Decimal("508"), Decimal("509"), Decimal("505"), Decimal("506")
        )
        result = s.on_bars([_BAR1, _BAR2, breakdown_bar])
        assert result is not None
        assert result.reference_price == Decimal("506")


class TestInsideRange:
    def test_returns_none_when_close_inside_range(self) -> None:
        s = _strategy()
        inside_bar = make_bar(
            "SPY", _dt(15, 30), Decimal("510"), Decimal("512"), Decimal("509"), Decimal("511")
        )
        result = s.on_bars([_BAR1, _BAR2, inside_bar])
        assert result is None


class TestStopLossPct:
    def test_buy_stop_loss_pct_is_positive_and_nonzero(self) -> None:
        s = _strategy()
        breakout_bar = make_bar(
            "SPY", _dt(15, 30), Decimal("513"), Decimal("516"), Decimal("512"), Decimal("515")
        )
        result = s.on_bars([_BAR1, _BAR2, breakout_bar])
        assert result is not None
        assert result.stop_loss_pct is not None
        assert result.stop_loss_pct > Decimal("0")

    def test_sell_stop_loss_pct_is_positive_and_nonzero(self) -> None:
        s = _strategy()
        breakdown_bar = make_bar(
            "SPY", _dt(15, 30), Decimal("508"), Decimal("509"), Decimal("505"), Decimal("506")
        )
        result = s.on_bars([_BAR1, _BAR2, breakdown_bar])
        assert result is not None
        assert result.stop_loss_pct is not None
        assert result.stop_loss_pct > Decimal("0")

    def test_buy_stop_loss_pct_formula(self) -> None:
        s = _strategy()
        # range_high=513, range_low=508, close=515
        # stop_loss_pct = (515-508)/515 + 0.001
        breakout_bar = make_bar(
            "SPY", _dt(15, 30), Decimal("513"), Decimal("516"), Decimal("512"), Decimal("515")
        )
        result = s.on_bars([_BAR1, _BAR2, breakout_bar])
        assert result is not None
        expected = (Decimal("515") - Decimal("508")) / Decimal("515") + Decimal("0.001")
        assert result.stop_loss_pct == expected

    def test_sell_stop_loss_pct_formula(self) -> None:
        s = _strategy()
        # range_high=513, range_low=508, close=506
        # stop_loss_pct = (513-506)/506 + 0.001
        breakdown_bar = make_bar(
            "SPY", _dt(15, 30), Decimal("508"), Decimal("509"), Decimal("505"), Decimal("506")
        )
        result = s.on_bars([_BAR1, _BAR2, breakdown_bar])
        assert result is not None
        expected = (Decimal("513") - Decimal("506")) / Decimal("506") + Decimal("0.001")
        assert result.stop_loss_pct == expected


class TestOnlySignalOnCrossover:
    def test_no_signal_if_already_above_range_high_on_prev_bar(self) -> None:
        """No crossover signal if prev bar already closed above range_high."""
        s = _strategy()
        # prev session bar already above range_high (513) → not a crossover
        already_above = make_bar(
            "SPY", _dt(15, 30), Decimal("514"), Decimal("516"), Decimal("513"), Decimal("514")
        )
        still_above = make_bar(
            "SPY", _dt(16, 0), Decimal("514"), Decimal("517"), Decimal("513"), Decimal("515")
        )
        result = s.on_bars([_BAR1, _BAR2, already_above, still_above])
        assert result is None

    def test_no_signal_if_already_below_range_low_on_prev_bar(self) -> None:
        """No crossover signal if prev bar already closed below range_low."""
        s = _strategy()
        already_below = make_bar(
            "SPY", _dt(15, 30), Decimal("508"), Decimal("509"), Decimal("505"), Decimal("507")
        )
        still_below = make_bar(
            "SPY", _dt(16, 0), Decimal("507"), Decimal("508"), Decimal("504"), Decimal("506")
        )
        result = s.on_bars([_BAR1, _BAR2, already_below, still_below])
        assert result is None

    def test_no_signal_after_breakout_falls_back_inside_range(self) -> None:
        """After an initial breakout, if price returns inside range, no signal."""
        s = _strategy()
        breakout_bar = make_bar(
            "SPY", _dt(15, 30), Decimal("513"), Decimal("516"), Decimal("512"), Decimal("515")
        )
        back_inside = make_bar(
            "SPY", _dt(16, 0), Decimal("514"), Decimal("514"), Decimal("510"), Decimal("511")
        )
        result = s.on_bars([_BAR1, _BAR2, breakout_bar, back_inside])
        assert result is None
