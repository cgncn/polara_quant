from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from polara.constants import validate_utc_datetime


class EventType(StrEnum):
    MARKET_DATA = "market_data"
    ORDER_REQUEST = "order_request"
    FILL = "fill"
    SIGNAL = "signal"
    TARGET_POSITION = "target_position"
    HEALTH_CHECK = "health_check"


class Event[T](BaseModel):
    model_config = ConfigDict(strict=True)

    event_id: UUID = Field(default_factory=uuid4)
    event_type: EventType
    payload: T
    published_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("published_at", mode="after")
    @classmethod
    def published_at_must_be_utc(cls, v: datetime) -> datetime:
        return validate_utc_datetime(v)


__all__ = ["EventType", "Event"]
