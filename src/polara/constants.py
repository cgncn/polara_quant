from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

TZ = ZoneInfo("UTC")
ZERO = Decimal("0")
POLARA_VERSION = "0.1.0"


def validate_utc_datetime(v: datetime) -> datetime:
    """Confirm a datetime is timezone-aware and UTC."""
    if v.tzinfo is None:
        raise ValueError("datetime must be timezone-aware (UTC required)")
    if v.utcoffset() != timedelta(0):
        raise ValueError(f"datetime must be UTC, got utcoffset={v.utcoffset()!r}")
    return v


__all__ = ["TZ", "ZERO", "POLARA_VERSION", "validate_utc_datetime"]
