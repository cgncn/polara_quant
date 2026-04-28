from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from polara.schemas.market import Bar

ET = ZoneInfo("America/New_York")
_NYSE_OPEN = (9, 30)
_NYSE_CLOSE = (16, 0)


def session_open_utc(d: date) -> datetime:
    """Return the NYSE open as a UTC-aware datetime for the given date."""
    local = datetime(d.year, d.month, d.day, *_NYSE_OPEN, tzinfo=ET)
    return local.astimezone(UTC)


def session_close_utc(d: date) -> datetime:
    """Return the NYSE close as a UTC-aware datetime for the given date."""
    local = datetime(d.year, d.month, d.day, *_NYSE_CLOSE, tzinfo=ET)
    return local.astimezone(UTC)


def is_session_bar(bar: Bar) -> bool:
    """True if bar.timestamp falls within NYSE trading hours (inclusive open, exclusive close)."""
    bar_et = bar.timestamp.astimezone(ET)
    bar_date = bar_et.date()
    open_utc = session_open_utc(bar_date)
    close_utc = session_close_utc(bar_date)
    return open_utc <= bar.timestamp < close_utc


def opening_range_end_utc(d: date, bar_size: str, n_bars: int) -> datetime:
    """Return the UTC datetime after which the opening range is complete.

    bar_size uses IB format: "15 mins" or "30 mins".
    n_bars=2 with bar_size="30 mins" means the opening range covers the first 60 minutes.
    """
    parts = bar_size.split()
    if len(parts) != 2 or parts[1] not in {"mins", "min"}:
        raise ValueError(f"Unsupported bar_size format: {bar_size!r}. Expected '<N> mins'.")
    minutes = int(parts[0])
    return session_open_utc(d) + timedelta(minutes=minutes * n_bars)


def get_session_bars(bars: list[Bar], session_date: date) -> list[Bar]:
    """Return only bars whose timestamp falls within the NYSE session on session_date."""
    open_utc = session_open_utc(session_date)
    close_utc = session_close_utc(session_date)
    return [b for b in bars if open_utc <= b.timestamp < close_utc]


def get_prev_session_bars(bars: list[Bar], session_date: date) -> list[Bar]:
    """Return bars from the trading session immediately before session_date.

    'Immediately before' means the most recent date in bars that is before session_date
    AND has at least one session bar.
    """
    candidate_dates = sorted(
        {d for b in bars if (d := b.timestamp.astimezone(ET).date()) < session_date},
        reverse=True,
    )
    for d in candidate_dates:
        session_bars = get_session_bars(bars, d)
        if session_bars:
            return session_bars
    return []
