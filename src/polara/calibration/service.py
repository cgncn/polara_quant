"""CalibrationService — persists and retrieves calibration results."""
import json
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import text

from polara.calibration.schemas import CalibrationResult

_CREATE = text("""
    CREATE TABLE IF NOT EXISTS calibration_results (
        id TEXT PRIMARY KEY,
        strategy_id TEXT NOT NULL,
        calibrated_at TEXT NOT NULL,
        bar_size TEXT NOT NULL,
        lookback_bars INTEGER NOT NULL,
        rolling_sharpe TEXT NOT NULL,
        size_multiplier TEXT NOT NULL,
        prev_params TEXT NOT NULL,
        best_params TEXT NOT NULL,
        param_sharpe_improvement TEXT NOT NULL
    )
""")

_INSERT = text("""
    INSERT INTO calibration_results
        (id, strategy_id, calibrated_at, bar_size, lookback_bars,
         rolling_sharpe, size_multiplier, prev_params, best_params,
         param_sharpe_improvement)
    VALUES
        (:id, :strategy_id, :calibrated_at, :bar_size, :lookback_bars,
         :rolling_sharpe, :size_multiplier, :prev_params, :best_params,
         :param_sharpe_improvement)
""")

_SELECT_LATEST = text("""
    SELECT strategy_id, calibrated_at, bar_size, lookback_bars,
           rolling_sharpe, size_multiplier, prev_params, best_params,
           param_sharpe_improvement
    FROM calibration_results
    WHERE strategy_id = :strategy_id
    ORDER BY calibrated_at DESC
    LIMIT 1
""")

_SELECT_HISTORY = text("""
    SELECT strategy_id, calibrated_at, bar_size, lookback_bars,
           rolling_sharpe, size_multiplier, prev_params, best_params,
           param_sharpe_improvement
    FROM calibration_results
    WHERE strategy_id = :strategy_id
    ORDER BY calibrated_at DESC
    LIMIT :limit
""")


def _row_to_result(row: tuple) -> CalibrationResult:
    calibrated_at = datetime.fromisoformat(row[1])
    if calibrated_at.tzinfo is None:
        raise ValueError(f"Stored calibrated_at is naive (no tzinfo): {row[1]!r}")
    return CalibrationResult(
        strategy_id=row[0],
        calibrated_at=calibrated_at,
        bar_size=row[2],
        lookback_bars=row[3],
        rolling_sharpe=Decimal(row[4]),
        size_multiplier=Decimal(row[5]),
        prev_params=json.loads(row[6]),
        best_params=json.loads(row[7]),
        param_sharpe_improvement=Decimal(row[8]),
    )


class CalibrationService:
    """Persist and retrieve CalibrationResult records."""

    def __init__(self, db_session_factory) -> None:
        self._db = db_session_factory

    async def migrate(self) -> None:
        async with self._db() as db:
            await db.execute(_CREATE)
            await db.commit()

    async def save(self, result: CalibrationResult) -> None:
        async with self._db() as db:
            await db.execute(
                _INSERT,
                {
                    "id": str(uuid4()),
                    "strategy_id": result.strategy_id,
                    "calibrated_at": result.calibrated_at.isoformat(),
                    "bar_size": result.bar_size,
                    "lookback_bars": result.lookback_bars,
                    "rolling_sharpe": str(result.rolling_sharpe),
                    "size_multiplier": str(result.size_multiplier),
                    "prev_params": json.dumps(result.prev_params),
                    "best_params": json.dumps(result.best_params),
                    "param_sharpe_improvement": str(result.param_sharpe_improvement),
                },
            )
            await db.commit()

    async def latest(self, strategy_id: str) -> CalibrationResult | None:
        async with self._db() as db:
            cursor = await db.execute(_SELECT_LATEST, {"strategy_id": strategy_id})
            row = cursor.fetchone()
        if row is None:
            return None
        return _row_to_result(row)

    async def history(self, strategy_id: str, limit: int = 10) -> list[CalibrationResult]:
        async with self._db() as db:
            cursor = await db.execute(
                _SELECT_HISTORY, {"strategy_id": strategy_id, "limit": limit}
            )
            rows = cursor.fetchall()
        return [_row_to_result(row) for row in rows]


__all__ = ["CalibrationService"]
