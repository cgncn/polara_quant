"""DashboardService — read-only queries powering the dashboard UI."""
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text


class DashboardService:
    def __init__(self, db_session_factory: Any) -> None:
        self._db = db_session_factory

    async def today_summary(self) -> dict:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        async with self._db() as db:
            row = (await db.execute(
                text("SELECT * FROM daily_summary WHERE trade_date = :d"),
                {"d": today},
            )).fetchone()
            trades = (await db.execute(
                text("""
                    SELECT strategy_id, symbol, side, quantity,
                           entry_price, exit_price, realised_pnl,
                           entry_at, exit_at, status, commission
                    FROM trades WHERE trade_date = :d
                    ORDER BY entry_at DESC
                """),
                {"d": today},
            )).fetchall()

        trade_list = [dict(t._mapping) for t in trades]
        if row:
            net_pnl = Decimal(str(row.net_pnl))
            trade_count = row.trade_count or 0
            win_count = row.win_count or 0
            win_rate = round((win_count / trade_count * 100) if trade_count else 0, 1)
            return {
                "date": today,
                "net_pnl": str(net_pnl),
                "trade_count": trade_count,
                "win_count": win_count,
                "win_rate": win_rate,
                "end_nav": str(row.end_nav) if row.end_nav else None,
                "trades": trade_list,
            }
        return {
            "date": today,
            "net_pnl": "0",
            "trade_count": 0,
            "win_count": 0,
            "win_rate": 0.0,
            "end_nav": None,
            "trades": trade_list,
        }

    async def pnl_history(self, days: int = 30) -> list[dict]:
        async with self._db() as db:
            rows = (await db.execute(
                text("""
                    SELECT trade_date, net_pnl, trade_count, win_count,
                           gross_win, gross_loss, end_nav
                    FROM daily_summary
                    ORDER BY trade_date DESC
                    LIMIT :limit
                """),
                {"limit": days},
            )).fetchall()
        result = []
        for r in rows:
            tc = r.trade_count or 0
            wc = r.win_count or 0
            result.append({
                "date": r.trade_date,
                "net_pnl": str(r.net_pnl),
                "trade_count": tc,
                "win_count": wc,
                "win_rate": round((wc / tc * 100) if tc else 0, 1),
                "end_nav": str(r.end_nav) if r.end_nav else None,
            })
        return result

    async def trades_for_date(self, date: str) -> list[dict]:
        async with self._db() as db:
            rows = (await db.execute(
                text("""
                    SELECT strategy_id, symbol, side, quantity,
                           entry_price, exit_price, realised_pnl,
                           entry_at, exit_at, status, commission
                    FROM trades WHERE trade_date = :d
                    ORDER BY entry_at DESC
                """),
                {"d": date},
            )).fetchall()
        return [dict(r._mapping) for r in rows]

    async def strategy_performance(self) -> list[dict]:
        async with self._db() as db:
            rows = (await db.execute(text("""
                SELECT
                    strategy_id,
                    COUNT(*) AS trade_count,
                    SUM(CASE WHEN CAST(realised_pnl AS REAL) > 0 THEN 1 ELSE 0 END) AS win_count,
                    SUM(CAST(realised_pnl AS REAL)) AS net_pnl,
                    AVG(CASE WHEN CAST(realised_pnl AS REAL) > 0
                        THEN CAST(realised_pnl AS REAL) END) AS avg_win,
                    AVG(CASE WHEN CAST(realised_pnl AS REAL) < 0
                        THEN CAST(realised_pnl AS REAL) END) AS avg_loss,
                    SUM(CASE WHEN CAST(realised_pnl AS REAL) > 0
                        THEN CAST(realised_pnl AS REAL) ELSE 0 END) AS gross_win,
                    ABS(SUM(CASE WHEN CAST(realised_pnl AS REAL) < 0
                        THEN CAST(realised_pnl AS REAL) ELSE 0 END)) AS gross_loss
                FROM trades WHERE status = 'closed'
                GROUP BY strategy_id
                ORDER BY net_pnl DESC
            """))).fetchall()
        return [_strategy_row(r) for r in rows]

    async def symbol_performance(self) -> list[dict]:
        async with self._db() as db:
            rows = (await db.execute(text("""
                SELECT
                    symbol,
                    COUNT(*) AS trade_count,
                    SUM(CASE WHEN CAST(realised_pnl AS REAL) > 0 THEN 1 ELSE 0 END) AS win_count,
                    SUM(CAST(realised_pnl AS REAL)) AS net_pnl,
                    AVG(CASE WHEN CAST(realised_pnl AS REAL) > 0
                        THEN CAST(realised_pnl AS REAL) END) AS avg_win,
                    AVG(CASE WHEN CAST(realised_pnl AS REAL) < 0
                        THEN CAST(realised_pnl AS REAL) END) AS avg_loss,
                    SUM(CASE WHEN CAST(realised_pnl AS REAL) > 0
                        THEN CAST(realised_pnl AS REAL) ELSE 0 END) AS gross_win,
                    ABS(SUM(CASE WHEN CAST(realised_pnl AS REAL) < 0
                        THEN CAST(realised_pnl AS REAL) ELSE 0 END)) AS gross_loss
                FROM trades WHERE status = 'closed'
                GROUP BY symbol
                ORDER BY net_pnl DESC
            """))).fetchall()
        return [_strategy_row(r) for r in rows]

    async def trades_filtered(
        self,
        *,
        date: str | None = None,
        strategy_id: str | None = None,
        symbol: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        clauses = ["1=1"]
        params: dict = {"limit": limit}
        if date:
            clauses.append("trade_date = :date")
            params["date"] = date
        if strategy_id:
            clauses.append("strategy_id = :strategy_id")
            params["strategy_id"] = strategy_id
        if symbol:
            clauses.append("symbol = :symbol")
            params["symbol"] = symbol
        where = " AND ".join(clauses)
        async with self._db() as db:
            rows = (await db.execute(
                text(f"""
                    SELECT strategy_id, symbol, side, quantity,
                           entry_price, exit_price, realised_pnl,
                           entry_at, exit_at, status, commission, trade_date
                    FROM trades WHERE {where}
                    ORDER BY entry_at DESC LIMIT :limit
                """),
                params,
            )).fetchall()
        return [dict(r._mapping) for r in rows]


def _strategy_row(r: Any) -> dict:
    tc = r.trade_count or 0
    wc = r.win_count or 0
    gross_win = float(r.gross_win or 0)
    gross_loss = float(r.gross_loss or 0)
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss else None
    return {
        "strategy_id": getattr(r, "strategy_id", None),
        "symbol": getattr(r, "symbol", None),
        "trade_count": tc,
        "win_count": wc,
        "win_rate": round((wc / tc * 100) if tc else 0, 1),
        "net_pnl": str(round(r.net_pnl or 0, 2)),
        "avg_win": str(round(r.avg_win or 0, 2)),
        "avg_loss": str(round(r.avg_loss or 0, 2)),
        "profit_factor": str(profit_factor) if profit_factor is not None else None,
    }
