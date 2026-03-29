from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from polara.constants import validate_utc_datetime


class Bar(BaseModel):
    model_config = ConfigDict(strict=True)

    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int

    @field_validator("timestamp", mode="after")
    @classmethod
    def timestamp_must_be_utc(cls, v: datetime) -> datetime:
        return validate_utc_datetime(v)

    @field_validator("open", "high", "low", "close", mode="before")
    @classmethod
    def reject_float(cls, v: object) -> object:
        if isinstance(v, float):
            raise ValueError("float is not allowed for price fields; use Decimal")
        return v

    @field_validator("open", "high", "low", "close", mode="after")
    @classmethod
    def price_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("price must be > 0")
        return v

    @field_validator("volume", mode="after")
    @classmethod
    def volume_must_be_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("volume must be >= 0")
        return v


class Quote(BaseModel):
    model_config = ConfigDict(strict=True)

    symbol: str
    timestamp: datetime
    bid: Decimal
    ask: Decimal
    bid_size: int
    ask_size: int

    @field_validator("timestamp", mode="after")
    @classmethod
    def timestamp_must_be_utc(cls, v: datetime) -> datetime:
        return validate_utc_datetime(v)

    @field_validator("bid", "ask", mode="before")
    @classmethod
    def reject_float(cls, v: object) -> object:
        if isinstance(v, float):
            raise ValueError("float is not allowed for price fields; use Decimal")
        return v

    @field_validator("bid", "ask", mode="after")
    @classmethod
    def price_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("price must be > 0")
        return v

    @field_validator("ask", mode="after")
    @classmethod
    def ask_must_be_gte_bid(cls, v: Decimal, info: object) -> Decimal:
        # info.data contains already-validated fields
        data = getattr(info, "data", {})
        bid = data.get("bid")
        if bid is not None and v < bid:
            raise ValueError(f"ask ({v}) must be >= bid ({bid})")
        return v

    @field_validator("bid_size", "ask_size", mode="after")
    @classmethod
    def size_must_be_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("size must be >= 0")
        return v


__all__ = ["Bar", "Quote"]
