"""CalibrationResult schema."""
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from polara.constants import validate_utc_datetime


class CalibrationResult(BaseModel):
    model_config = ConfigDict(strict=True)

    strategy_id: str
    calibrated_at: datetime
    bar_size: str
    lookback_bars: int
    rolling_sharpe: Decimal
    size_multiplier: Decimal
    prev_params: dict
    best_params: dict
    param_sharpe_improvement: Decimal

    @field_validator("calibrated_at", mode="after")
    @classmethod
    def must_be_utc(cls, v: datetime) -> datetime:
        return validate_utc_datetime(v)

    @field_validator("rolling_sharpe", "size_multiplier", "param_sharpe_improvement", mode="before")
    @classmethod
    def reject_float(cls, v: object) -> object:
        if isinstance(v, float):
            raise ValueError("use Decimal not float")
        return v


__all__ = ["CalibrationResult"]
