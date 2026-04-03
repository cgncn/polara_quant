"""BacktestService — persists and retrieves backtest results."""
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import text

from polara.backtester.schemas import BacktestResult

_INSERT = text("""
    INSERT INTO backtest_results
        (id, strategy_id, run_at, bar_size, num_bars,
         sharpe_ratio, max_drawdown_pct, win_rate_pct,
         total_return_pct, num_trades, passed, notes)
    VALUES
        (:id, :strategy_id, :run_at, :bar_size, :num_bars,
         :sharpe_ratio, :max_drawdown_pct, :win_rate_pct,
         :total_return_pct, :num_trades, :passed, :notes)
""")

_SELECT_BY_STRATEGY = text("""
    SELECT id, strategy_id, run_at, bar_size, num_bars,
           sharpe_ratio, max_drawdown_pct, win_rate_pct,
           total_return_pct, num_trades, passed, notes
    FROM backtest_results
    WHERE strategy_id = :strategy_id
    ORDER BY run_at DESC
    LIMIT :limit
""")

_HAS_PASSING = text("""
    SELECT COUNT(*) FROM backtest_results
    WHERE strategy_id = :strategy_id AND passed = 1
""")


class BacktestService:
    """Persist and retrieve BacktestResult records."""

    def __init__(self, db_session_factory) -> None:
        self._db = db_session_factory

    async def save(self, result: BacktestResult) -> None:
        """Persist a BacktestResult to the database."""
        async with self._db() as db:
            await db.execute(
                _INSERT,
                {
                    "id": str(uuid4()),
                    "strategy_id": result.strategy_id,
                    "run_at": result.run_at.isoformat(),
                    "bar_size": result.bar_size,
                    "num_bars": result.num_bars,
                    "sharpe_ratio": str(result.sharpe_ratio),
                    "max_drawdown_pct": str(result.max_drawdown_pct),
                    "win_rate_pct": str(result.win_rate_pct),
                    "total_return_pct": str(result.total_return_pct),
                    "num_trades": result.num_trades,
                    "passed": 1 if result.passed else 0,
                    "notes": result.notes,
                },
            )
            await db.commit()

    async def get_results(
        self, strategy_id: str, limit: int = 10
    ) -> list[BacktestResult]:
        """Return the most recent backtest results for a strategy, newest first."""
        async with self._db() as db:
            cursor = await db.execute(
                _SELECT_BY_STRATEGY,
                {"strategy_id": strategy_id, "limit": limit},
            )
            rows = cursor.fetchall()

        return [
            BacktestResult(
                strategy_id=row[1],
                run_at=(
                    datetime.fromisoformat(row[2]).replace(tzinfo=UTC)
                    if datetime.fromisoformat(row[2]).tzinfo is None
                    else datetime.fromisoformat(row[2])
                ),
                bar_size=row[3],
                num_bars=row[4],
                sharpe_ratio=Decimal(row[5]),
                max_drawdown_pct=Decimal(row[6]),
                win_rate_pct=Decimal(row[7]),
                total_return_pct=Decimal(row[8]),
                num_trades=row[9],
                passed=bool(row[10]),
                notes=row[11],
            )
            for row in rows
        ]

    async def has_passing_result(self, strategy_id: str) -> bool:
        """Return True if the strategy has at least one passing backtest result."""
        async with self._db() as db:
            result = await db.execute(
                _HAS_PASSING, {"strategy_id": strategy_id}
            )
            count = result.scalar()
        return (count or 0) > 0


__all__ = ["BacktestService"]
