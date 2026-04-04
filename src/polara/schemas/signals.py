from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from polara.constants import ZERO, validate_utc_datetime

_MINUS_ONE = Decimal("-1")
_ONE = Decimal("1")


class Signal(BaseModel):
    model_config = ConfigDict(strict=True)

    signal_id: UUID
    strategy_id: str
    symbol: str
    strength: Decimal
    generated_at: datetime
    reference_price: Decimal | None = None
    stop_loss_pct: Decimal | None = None
    take_profit_pct: Decimal | None = None

    @field_validator("reference_price", mode="before")
    @classmethod
    def reject_float_price(cls, v: object) -> object:
        if isinstance(v, float):
            raise ValueError("reference_price must be Decimal, not float")
        return v

    @field_validator("stop_loss_pct", "take_profit_pct", mode="before")
    @classmethod
    def reject_float_pct(cls, v: object) -> object:
        if isinstance(v, float):
            raise ValueError("stop_loss_pct and take_profit_pct must be Decimal, not float")
        return v

    @field_validator("generated_at", mode="after")
    @classmethod
    def generated_at_must_be_utc(cls, v: datetime) -> datetime:
        return validate_utc_datetime(v)

    @field_validator("strength", mode="before")
    @classmethod
    def reject_float(cls, v: object) -> object:
        if isinstance(v, float):
            raise ValueError("float is not allowed for strength; use Decimal")
        return v

    @field_validator("strength", mode="after")
    @classmethod
    def strength_in_range(cls, v: Decimal) -> Decimal:
        if v < _MINUS_ONE or v > _ONE:
            raise ValueError(f"strength must be in range [-1, 1], got {v}")
        return v


class TargetPosition(BaseModel):
    model_config = ConfigDict(strict=True)

    position_id: UUID = Field(default_factory=uuid4)
    strategy_id: str
    symbol: str
    target_weight: Decimal
    rationale: str
    computed_at: datetime

    @field_validator("computed_at", mode="after")
    @classmethod
    def computed_at_must_be_utc(cls, v: datetime) -> datetime:
        return validate_utc_datetime(v)

    @field_validator("target_weight", mode="before")
    @classmethod
    def reject_float(cls, v: object) -> object:
        if isinstance(v, float):
            raise ValueError("float is not allowed for target_weight; use Decimal")
        return v

    @field_validator("target_weight", mode="after")
    @classmethod
    def target_weight_in_range(cls, v: Decimal) -> Decimal:
        if v < ZERO or v > _ONE:
            raise ValueError(f"target_weight must be in range [0, 1], got {v}")
        return v


__all__ = ["Signal", "TargetPosition"]
