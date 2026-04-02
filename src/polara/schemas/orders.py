from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

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

    @model_validator(mode="before")
    @classmethod
    def _coerce_json_types(cls, data: object) -> object:
        """Pre-process JSON dict input before strict field validation.

        FastAPI's default body binding calls model_validate (Python mode).
        Under strict=True, strings are rejected for UUID, datetime, and Decimal
        fields.  This validator normalises those types from their JSON string
        representations so the route can be declared as a direct annotated
        parameter (enabling OpenAPI requestBody generation) while still
        enforcing strict type checking after coercion.
        """
        if not isinstance(data, dict):
            return data
        result = dict(data)
        # str → UUID
        if isinstance(result.get("order_id"), str):
            try:
                result["order_id"] = UUID(result["order_id"])
            except ValueError:
                pass  # let field validation produce the proper error
        # str → datetime
        if isinstance(result.get("requested_at"), str):
            try:
                result["requested_at"] = datetime.fromisoformat(result["requested_at"])
            except ValueError:
                pass
        # str → Decimal for numeric fields (floats still rejected by field validators)
        for field in ("quantity", "limit_price"):
            val = result.get(field)
            if isinstance(val, str):
                try:
                    result[field] = Decimal(val)
                except InvalidOperation:
                    pass
        return result

    @field_validator("requested_at", mode="after")
    @classmethod
    def requested_at_must_be_utc(cls, v: datetime) -> datetime:
        return validate_utc_datetime(v)

    @field_validator("quantity", "limit_price", mode="before")
    @classmethod
    def reject_float(cls, v: object) -> object:
        if v is None:
            return v  # None is valid for Optional[Decimal] fields
        if isinstance(v, float):
            raise ValueError("use Decimal, not float, for monetary values")
        if isinstance(v, str):
            return Decimal(v)
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
            raise ValueError("filled_quantity and fill_price must be > 0")
        return v

    @field_validator("commission", mode="after")
    @classmethod
    def commission_must_be_non_negative(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError("commission must be >= 0")
        return v


__all__ = ["OrderSide", "OrderRequest", "Fill"]
