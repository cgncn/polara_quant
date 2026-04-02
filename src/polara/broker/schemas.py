"""IB-specific Pydantic models for the broker adapter."""
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from polara.constants import validate_utc_datetime
from polara.schemas.orders import Fill

# Status values that mirror the orders table CHECK constraint
OrderStatusLiteral = Literal["pending", "submitted", "filled", "cancelled", "error"]


class AccountInfo(BaseModel):
    model_config = ConfigDict(strict=True)

    net_liquidation: Decimal
    cash: Decimal
    unrealised_pnl: Decimal
    realised_pnl: Decimal
    currency: str
    timestamp: datetime  # must be UTC-aware

    @field_validator("timestamp", mode="after")
    @classmethod
    def timestamp_must_be_utc(cls, v: datetime) -> datetime:
        return validate_utc_datetime(v)


class Position(BaseModel):
    model_config = ConfigDict(strict=True)

    symbol: str
    quantity: Decimal
    avg_cost: Decimal
    unrealised_pnl: Decimal
    updated_at: datetime  # must be UTC-aware

    @field_validator("updated_at", mode="after")
    @classmethod
    def updated_at_must_be_utc(cls, v: datetime) -> datetime:
        return validate_utc_datetime(v)


class PnLSnapshot(BaseModel):
    model_config = ConfigDict(strict=True)

    net_liquidation: Decimal
    cash: Decimal
    unrealised_pnl: Decimal
    realised_pnl: Decimal
    snapshot_at: datetime  # must be UTC-aware

    @field_validator("snapshot_at", mode="after")
    @classmethod
    def snapshot_at_must_be_utc(cls, v: datetime) -> datetime:
        return validate_utc_datetime(v)


class BrokerStatus(BaseModel):
    model_config = ConfigDict(strict=True)

    connected: bool
    ib_server_time: datetime | None
    account_id: str | None

    @field_validator("ib_server_time", mode="after")
    @classmethod
    def ib_server_time_must_be_utc(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        return validate_utc_datetime(v)


class OrderStatus(BaseModel):
    model_config = ConfigDict(strict=True)

    order_id: UUID
    ib_order_id: int | None
    status: OrderStatusLiteral
    submitted_at: datetime  # must be UTC-aware
    filled_at: datetime | None

    @field_validator("submitted_at", mode="after")
    @classmethod
    def submitted_at_must_be_utc(cls, v: datetime) -> datetime:
        return validate_utc_datetime(v)

    @field_validator("filled_at", mode="after")
    @classmethod
    def filled_at_must_be_utc(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        return validate_utc_datetime(v)


class OrderWithFills(BaseModel):
    model_config = ConfigDict(strict=True)

    order_id: UUID
    ib_order_id: int | None
    status: OrderStatusLiteral
    submitted_at: datetime
    filled_at: datetime | None
    fills: list[Fill]

    @field_validator("submitted_at", mode="after")
    @classmethod
    def submitted_at_must_be_utc(cls, v: datetime) -> datetime:
        return validate_utc_datetime(v)

    @field_validator("filled_at", mode="after")
    @classmethod
    def filled_at_must_be_utc(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        return validate_utc_datetime(v)


__all__ = [
    "AccountInfo",
    "Position",
    "PnLSnapshot",
    "BrokerStatus",
    "OrderStatus",
    "OrderWithFills",
]
