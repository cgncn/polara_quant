"""StrategyStatusService — manages strategy status in the DB.

Owns all reads and writes to strategies.status. Does NOT touch the
in-memory StrategyRegistry.
"""
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import text

StrategyStatus = Literal["inactive", "paper", "paused", "live"]

_GET_STATUS = text("SELECT status FROM strategies WHERE id = :id")
_SET_STATUS = text("UPDATE strategies SET status = :status WHERE id = :id")
_UPSERT = text("""
    INSERT INTO strategies (id, name, status, created_at)
    VALUES (:id, :name, :status, :created_at)
    ON CONFLICT (id) DO NOTHING
""")


class StrategyStatusService:
    """DB-backed strategy status manager. Uses strategy_id string as DB primary key."""

    def __init__(self, db_session_factory) -> None:
        self._db = db_session_factory

    async def get_status(self, strategy_id: str) -> StrategyStatus | None:
        """Return current status, or None if no row exists."""
        async with self._db() as db:
            result = await db.execute(_GET_STATUS, {"id": strategy_id})
            row = result.fetchone()
        if row is None:
            return None
        return row[0]

    async def set_status(self, strategy_id: str, status: StrategyStatus) -> None:
        """Update status. Raises ValueError if strategy_id not found."""
        async with self._db() as db:
            result = await db.execute(_SET_STATUS, {"status": status, "id": strategy_id})
            await db.commit()
            if result.rowcount == 0:
                raise ValueError(f"Strategy '{strategy_id}' not found in DB")

    async def ensure_registered(
        self,
        strategy_id: str,
        name: str,
        status: StrategyStatus = "paper",
    ) -> None:
        """UPSERT: create row if missing. Does not overwrite existing status."""
        async with self._db() as db:
            await db.execute(_UPSERT, {
                "id": strategy_id,
                "name": name,
                "status": status,
                "created_at": datetime.now(UTC).isoformat(),
            })
            await db.commit()
