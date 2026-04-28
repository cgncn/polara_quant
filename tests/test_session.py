from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from polara.market_data.session import (
    ET,
    get_prev_session_bars,
    get_session_bars,
    is_session_bar,
    opening_range_end_utc,
    session_close_utc,
    session_open_utc,
)
from polara.schemas.market import Bar


def make_bar(ts: datetime, symbol: str = "AAPL") -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=ts,
        open=Decimal("100.00"),
        high=Decimal("101.00"),
        low=Decimal("99.00"),
        close=Decimal("100.50"),
        volume=1000,
    )


# ---------------------------------------------------------------------------
# session_open_utc / session_close_utc
# ---------------------------------------------------------------------------


class TestSessionOpenClose:
    def test_returns_utc_aware(self):
        d = date(2024, 7, 15)
        open_dt = session_open_utc(d)
        close_dt = session_close_utc(d)
        assert open_dt.tzinfo is not None
        assert open_dt.utcoffset() == timedelta(0)
        assert close_dt.tzinfo is not None
        assert close_dt.utcoffset() == timedelta(0)

    def test_dst_summer_july(self):
        # July: ET = UTC-4, so 9:30 ET = 13:30 UTC
        d = date(2024, 7, 15)
        open_utc = session_open_utc(d)
        assert open_utc.hour == 13
        assert open_utc.minute == 30

    def test_dst_winter_march_before_dst(self):
        # March 1 (before DST): ET = UTC-5, so 9:30 ET = 14:30 UTC
        d = date(2024, 3, 1)
        open_utc = session_open_utc(d)
        assert open_utc.hour == 14
        assert open_utc.minute == 30

    def test_close_summer(self):
        # July: ET = UTC-4, so 16:00 ET = 20:00 UTC
        d = date(2024, 7, 15)
        close_utc = session_close_utc(d)
        assert close_utc.hour == 20
        assert close_utc.minute == 0

    def test_close_winter(self):
        # Winter: ET = UTC-5, so 16:00 ET = 21:00 UTC
        d = date(2024, 3, 1)
        close_utc = session_close_utc(d)
        assert close_utc.hour == 21
        assert close_utc.minute == 0

    def test_open_and_close_same_date(self):
        d = date(2024, 1, 10)
        open_utc = session_open_utc(d)
        close_utc = session_close_utc(d)
        assert close_utc > open_utc
        assert close_utc - open_utc == timedelta(hours=6, minutes=30)


# ---------------------------------------------------------------------------
# is_session_bar
# ---------------------------------------------------------------------------


class TestIsSessionBar:
    def test_bar_at_open_is_true(self):
        # March (winter): open = 14:30 UTC
        ts = datetime(2024, 3, 1, 14, 30, tzinfo=UTC)
        bar = make_bar(ts)
        assert is_session_bar(bar) is True

    def test_bar_one_minute_before_open_is_false(self):
        ts = datetime(2024, 3, 1, 14, 29, tzinfo=UTC)
        bar = make_bar(ts)
        assert is_session_bar(bar) is False

    def test_bar_at_close_is_false(self):
        # March (winter): close = 21:00 UTC
        ts = datetime(2024, 3, 1, 21, 0, tzinfo=UTC)
        bar = make_bar(ts)
        assert is_session_bar(bar) is False

    def test_bar_one_minute_before_close_is_true(self):
        ts = datetime(2024, 3, 1, 20, 59, tzinfo=UTC)
        bar = make_bar(ts)
        assert is_session_bar(bar) is True

    def test_bar_after_close_is_false(self):
        ts = datetime(2024, 3, 1, 21, 1, tzinfo=UTC)
        bar = make_bar(ts)
        assert is_session_bar(bar) is False

    def test_summer_bar_at_open_is_true(self):
        # July: open = 13:30 UTC
        ts = datetime(2024, 7, 15, 13, 30, tzinfo=UTC)
        bar = make_bar(ts)
        assert is_session_bar(bar) is True

    def test_summer_bar_before_open_is_false(self):
        ts = datetime(2024, 7, 15, 13, 29, tzinfo=UTC)
        bar = make_bar(ts)
        assert is_session_bar(bar) is False


# ---------------------------------------------------------------------------
# opening_range_end_utc
# ---------------------------------------------------------------------------


class TestOpeningRangeEndUtc:
    def test_two_30min_bars_equals_60_minutes(self):
        d = date(2024, 7, 15)
        end = opening_range_end_utc(d, "30 mins", 2)
        expected = session_open_utc(d) + timedelta(minutes=60)
        assert end == expected

    def test_four_15min_bars_equals_60_minutes(self):
        d = date(2024, 7, 15)
        end = opening_range_end_utc(d, "15 mins", 4)
        expected = session_open_utc(d) + timedelta(minutes=60)
        assert end == expected

    def test_one_30min_bar(self):
        d = date(2024, 3, 1)
        end = opening_range_end_utc(d, "30 mins", 1)
        expected = session_open_utc(d) + timedelta(minutes=30)
        assert end == expected

    def test_result_is_utc_aware(self):
        end = opening_range_end_utc(date(2024, 7, 15), "15 mins", 2)
        assert end.tzinfo is not None
        assert end.utcoffset() == timedelta(0)

    @pytest.mark.parametrize("bad_size", ["1 day", "1 hour"])
    def test_invalid_bar_size_raises(self, bad_size: str):
        with pytest.raises(ValueError, match="Unsupported bar_size format"):
            opening_range_end_utc(date(2024, 7, 15), bad_size, 1)


# ---------------------------------------------------------------------------
# get_session_bars
# ---------------------------------------------------------------------------


class TestGetSessionBars:
    def _make_session_bars(self, session_date: date) -> list[Bar]:
        open_utc = session_open_utc(session_date)
        return [
            make_bar(open_utc),
            make_bar(open_utc + timedelta(minutes=30)),
            make_bar(open_utc + timedelta(hours=1)),
        ]

    def test_filters_to_session_only(self):
        d = date(2024, 7, 15)
        open_utc = session_open_utc(d)
        bars = [
            make_bar(open_utc - timedelta(minutes=30)),  # pre-market
            make_bar(open_utc),                          # session
            make_bar(open_utc + timedelta(hours=3)),     # session
            make_bar(session_close_utc(d)),              # post-market (close is exclusive)
        ]
        result = get_session_bars(bars, d)
        assert len(result) == 2
        assert result[0].timestamp == open_utc
        assert result[1].timestamp == open_utc + timedelta(hours=3)

    def test_empty_for_weekend_date(self):
        # 2024-07-13 is a Saturday
        weekend = date(2024, 7, 13)
        monday = date(2024, 7, 15)
        bars = self._make_session_bars(monday)
        result = get_session_bars(bars, weekend)
        assert result == []

    def test_returns_all_session_bars_for_matching_date(self):
        d = date(2024, 7, 15)
        bars = self._make_session_bars(d)
        result = get_session_bars(bars, d)
        assert len(result) == 3


# ---------------------------------------------------------------------------
# get_prev_session_bars
# ---------------------------------------------------------------------------


class TestGetPrevSessionBars:
    def _bars_for_date(self, d: date) -> list[Bar]:
        open_utc = session_open_utc(d)
        return [
            make_bar(open_utc),
            make_bar(open_utc + timedelta(minutes=30)),
        ]

    def test_monday_returns_friday_bars(self):
        monday = date(2024, 7, 15)
        friday = date(2024, 7, 12)
        bars = self._bars_for_date(friday) + self._bars_for_date(monday)
        result = get_prev_session_bars(bars, monday)
        assert len(result) == 2
        assert all(b.timestamp.astimezone(ET).date() == friday for b in result)

    def test_skips_date_with_no_session_bars(self):
        # Wednesday has only a pre-market bar; Tuesday has session bars
        wednesday = date(2024, 7, 10)
        tuesday = date(2024, 7, 9)
        thursday = date(2024, 7, 11)

        wed_open = session_open_utc(wednesday)
        pre_market_bar = make_bar(wed_open - timedelta(minutes=30))  # before session

        bars = (
            self._bars_for_date(tuesday)
            + [pre_market_bar]
            + self._bars_for_date(thursday)
        )
        result = get_prev_session_bars(bars, thursday)
        # Wednesday has no session bars, so should find Tuesday
        assert len(result) == 2
        assert all(b.timestamp.astimezone(ET).date() == tuesday for b in result)

    def test_returns_empty_when_no_prior_bars(self):
        d = date(2024, 7, 15)
        bars = self._bars_for_date(d)
        result = get_prev_session_bars(bars, d)
        assert result == []

    def test_returns_empty_for_empty_input(self):
        result = get_prev_session_bars([], date(2024, 7, 15))
        assert result == []

    def test_picks_most_recent_prior_session(self):
        monday = date(2024, 7, 15)
        friday = date(2024, 7, 12)
        thursday = date(2024, 7, 11)
        bars = (
            self._bars_for_date(thursday)
            + self._bars_for_date(friday)
            + self._bars_for_date(monday)
        )
        result = get_prev_session_bars(bars, monday)
        assert all(b.timestamp.astimezone(ET).date() == friday for b in result)
