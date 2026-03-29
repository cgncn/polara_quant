from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from polara.constants import validate_utc_datetime

OrderSide = Literal["buy", "sell"]


class OrderRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    order_id: UUID
    symbol: str
    side: OrderSide
    quantity: Decimal
    limit_price: Decimal | None
    requested_at: datetime
    strategy_id: str

    @field_validator("requested_at", mode="after")
    @classmethod
    def requested_at_must_be_utc(cls, v: datetime) -> datetime:
        return validate_utc_datetime(v)

    @field_validator("quantity", "limit_price", mode="before")
    @classmethod
    def reject_float(cls, v: object) -> object:
        if isinstance(v, float):
            raise ValueError("float is not allowed for quantity/price fields; use Decimal")
        return v

    @field_validator("quantity", mode="after")
    @classmethod
    def quantity_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("quantity must be > 0")
        return v

    @field_validator("limit_price", mode="after")
    @classmethod
    def limit_price_must_be_positive(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v <= 0:
            raise ValueError("limit_price must be > 0")
        return v


class Fill(BaseModel):
    model_config = ConfigDict(strict=True)

    fill_id: UUID
    order_id: UUID
    symbol: str
    side: OrderSide
    filled_quantity: Decimal
    fill_price: Decimal
    commission: Decimal
    filled_at: datetime

    @field_validator("filled_at", mode="after")
    @classmethod
    def filled_at_must_be_utc(cls, v: datetime) -> datetime:
        return validate_utc_datetime(v)

    @field_validator("filled_quantity", "fill_price", "commission", mode="before")
    @classmethod
    def reject_float(cls, v: object) -> object:
        if isinstance(v, float):
            raise ValueError("float is not allowed for Decimal fields; use Decimal")
        return v

    @field_validator("filled_quantity", "fill_price", mode="after")
    @classmethod
    def must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("value must be > 0")
        return v

    @field_validator("commission", mode="after")
    @classmethod
    def commission_must_be_non_negative(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError("commission must be >= 0")
        return v


__all__ = ["OrderSide", "OrderRequest", "Fill"]
