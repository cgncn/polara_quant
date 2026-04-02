from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

TZ = ZoneInfo("UTC")
ZERO = Decimal("0")


def validate_utc_datetime(v: datetime) -> datetime:
    """
    Validate that a datetime is timezone-aware and has a UTC (zero) offset.

    Accepts any timezone with a zero UTC offset (UTC, Etc/UTC, timezone.utc,
    timezone(timedelta(0))). Rejects naive datetimes and non-UTC offsets.
    """
    if v.tzinfo is None:
        raise ValueError("datetime must be timezone-aware (UTC required)")
    if v.utcoffset() != timedelta(0):
        raise ValueError(f"datetime must be UTC, got utcoffset={v.utcoffset()!r}")
    return v


__all__ = ["TZ", "ZERO", "validate_utc_datetime"]
