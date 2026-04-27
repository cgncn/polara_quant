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


    async def performance_metrics(self) -> dict:
        """Institutional-grade aggregate performance metrics across all closed trades."""
        async with self._db() as db:
            row = (await db.execute(text("""
                SELECT
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
            """))).fetchone()
            nav_rows = (await db.execute(text("""
                SELECT end_nav FROM daily_summary
                WHERE end_nav IS NOT NULL
                ORDER BY trade_date ASC
            """))).fetchall()

        tc = row.trade_count or 0
        wc = row.win_count or 0
        gross_win = float(row.gross_win or 0)
        gross_loss = float(row.gross_loss or 0)
        avg_win = float(row.avg_win or 0)
        avg_loss = float(row.avg_loss or 0)
        net_pnl = float(row.net_pnl or 0)

        profit_factor = round(gross_win / gross_loss, 3) if gross_loss else None
        win_rate = wc / tc if tc else 0.0
        loss_rate = 1.0 - win_rate
        expectancy = round((win_rate * avg_win) + (loss_rate * avg_loss), 2) if tc else 0.0
        win_loss_ratio = round(abs(avg_win / avg_loss), 3) if avg_loss else None

        peak = 0.0
        max_dd_pct = 0.0
        max_dd_abs = 0.0
        for nr in nav_rows:
            nav = float(nr.end_nav)
            if nav > peak:
                peak = nav
            if peak > 0:
                dd_pct = (peak - nav) / peak
                dd_abs = peak - nav
                if dd_pct > max_dd_pct:
                    max_dd_pct = dd_pct
                    max_dd_abs = dd_abs

        recovery_factor = round(net_pnl / max_dd_abs, 3) if max_dd_abs > 0 else None
        return {
            "trade_count": tc,
            "win_count": wc,
            "win_rate": round(win_rate * 100, 1),
            "net_pnl": round(net_pnl, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "gross_win": round(gross_win, 2),
            "gross_loss": round(gross_loss, 2),
            "profit_factor": str(profit_factor) if profit_factor is not None else None,
            "recovery_factor": str(recovery_factor) if recovery_factor is not None else None,
            "win_loss_ratio": str(win_loss_ratio) if win_loss_ratio is not None else None,
            "expectancy": expectancy,
            "max_drawdown_pct": round(max_dd_pct * 100, 2),
            "max_drawdown_abs": round(max_dd_abs, 2),
        }

    async def equity_curve(self, days: int = 90) -> list[dict]:
        """NAV time-series with running drawdown for equity + underwater charts."""
        async with self._db() as db:
            rows = (await db.execute(text("""
                SELECT trade_date, end_nav, net_pnl FROM (
                    SELECT trade_date, end_nav, net_pnl
                    FROM daily_summary
                    WHERE end_nav IS NOT NULL
                    ORDER BY trade_date DESC
                    LIMIT :limit
                ) AS sub
                ORDER BY trade_date ASC
            """), {"limit": days})).fetchall()

        result: list[dict] = []
        peak = 0.0
        for r in rows:
            nav = float(r.end_nav)
            if nav > peak:
                peak = nav
            dd_pct = round((peak - nav) / peak * 100, 2) if peak > 0 else 0.0
            result.append({
                "date": r.trade_date,
                "nav": nav,
                "net_pnl": float(r.net_pnl or 0),
                "drawdown_pct": dd_pct,
            })
        return result

    async def pnl_distribution(self) -> dict:
        """Histogram bins of per-trade realised PnL for all closed trades."""
        async with self._db() as db:
            rows = (await db.execute(text("""
                SELECT CAST(realised_pnl AS REAL) AS pnl
                FROM trades WHERE status = 'closed' AND realised_pnl IS NOT NULL
            """))).fetchall()

        values = [float(r.pnl) for r in rows]
        if not values:
            return {"bins": [], "counts": [], "mean": 0.0, "std": 0.0}

        n = len(values)
        mean = sum(values) / n
        variance = sum((v - mean) ** 2 for v in values) / n if n > 1 else 0.0
        std = variance ** 0.5
        min_v, max_v = min(values), max(values)
        n_bins = min(20, max(5, n // 3))

        if max_v == min_v:
            return {
                "bins": [round(min_v, 2)], "counts": [n],
                "mean": round(mean, 2), "std": round(std, 2),
            }

        bin_size = (max_v - min_v) / n_bins
        counts = [0] * n_bins
        for v in values:
            idx = min(int((v - min_v) / bin_size), n_bins - 1)
            counts[idx] += 1
        bin_centers = [round(min_v + (i + 0.5) * bin_size, 2) for i in range(n_bins)]
        return {"bins": bin_centers, "counts": counts, "mean": round(mean, 2), "std": round(std, 2)}

    async def rolling_sharpe(self, days: int = 120, window: int = 30) -> list[dict]:
        """Annualised rolling Sharpe ratio computed over a sliding window of daily returns."""
        async with self._db() as db:
            rows = (await db.execute(text("""
                SELECT trade_date, net_pnl, start_nav FROM (
                    SELECT trade_date, net_pnl, start_nav
                    FROM daily_summary
                    WHERE start_nav IS NOT NULL AND start_nav > 0
                    ORDER BY trade_date DESC
                    LIMIT :limit
                ) AS sub
                ORDER BY trade_date ASC
            """), {"limit": days})).fetchall()

        daily_rets = [(r.trade_date, float(r.net_pnl or 0) / float(r.start_nav)) for r in rows]
        ann = 252 ** 0.5
        result: list[dict] = []
        for i in range(window - 1, len(daily_rets)):
            window_rets = [v for _, v in daily_rets[i - window + 1: i + 1]]
            wn = len(window_rets)
            mean_r = sum(window_rets) / wn
            var = sum((r - mean_r) ** 2 for r in window_rets) / (wn - 1) if wn > 1 else 0.0
            std_r = var ** 0.5
            sharpe = round((mean_r / std_r) * ann, 2) if std_r > 0 else 0.0
            result.append({"date": daily_rets[i][0], "sharpe": sharpe})
        return result

    async def active_positions(self) -> list[dict]:
        """Open (unfilled-exit) trades — current active positions."""
        async with self._db() as db:
            rows = (await db.execute(text("""
                SELECT strategy_id, symbol, side, quantity,
                       entry_price, entry_at, commission
                FROM trades WHERE status = 'open'
                ORDER BY entry_at DESC
            """))).fetchall()
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
