"""TradeService — records and closes trade lifecycle entries."""
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import text

_INSERT_TRADE = text("""
    INSERT INTO trades
        (id, strategy_id, symbol, side, quantity, entry_price,
         entry_at, commission, status, trade_date, entry_order_id)
    VALUES
        (:id, :strategy_id, :symbol, :side, :quantity, :entry_price,
         :entry_at, :commission, 'open', :trade_date, :entry_order_id)
    ON CONFLICT DO NOTHING
""")

_CLOSE_TRADE = text("""
    UPDATE trades SET
        exit_price    = :exit_price,
        exit_at       = :exit_at,
        realised_pnl  = :realised_pnl,
        commission    = :commission,
        status        = 'closed',
        exit_order_id = :exit_order_id
    WHERE entry_order_id = :entry_order_id AND status = 'open'
""")

_GET_OPEN_TRADE = text("""
    SELECT id, strategy_id, symbol, side, quantity, entry_price, commission
    FROM trades
    WHERE entry_order_id = :entry_order_id AND status = 'open'
    LIMIT 1
""")

_UPSERT_DAILY_SUMMARY = text("""
    INSERT INTO daily_summary
        (trade_date, net_pnl, trade_count, win_count, gross_win, gross_loss, updated_at)
    SELECT
        trade_date,
        COALESCE(SUM(CAST(realised_pnl AS REAL)), 0),
        COUNT(*),
        SUM(CASE WHEN CAST(realised_pnl AS REAL) > 0 THEN 1 ELSE 0 END),
        SUM(CASE WHEN CAST(realised_pnl AS REAL) > 0
            THEN CAST(realised_pnl AS REAL) ELSE 0 END),
        ABS(SUM(CASE WHEN CAST(realised_pnl AS REAL) < 0
            THEN CAST(realised_pnl AS REAL) ELSE 0 END)),
        :updated_at
    FROM trades
    WHERE trade_date = :trade_date AND status = 'closed'
    ON CONFLICT(trade_date) DO UPDATE SET
        net_pnl      = excluded.net_pnl,
        trade_count  = excluded.trade_count,
        win_count    = excluded.win_count,
        gross_win    = excluded.gross_win,
        gross_loss   = excluded.gross_loss,
        updated_at   = excluded.updated_at
""")

_UPDATE_DAILY_NAV = text("""
    UPDATE daily_summary SET
        end_nav    = :nav,
        updated_at = :updated_at
    WHERE trade_date = :trade_date
""")

_ENSURE_DAILY_SUMMARY = text("""
    INSERT INTO daily_summary
        (trade_date, net_pnl, trade_count, win_count, gross_win, gross_loss, start_nav, updated_at)
    VALUES (:trade_date, '0', 0, 0, '0', '0', :nav, :updated_at)
    ON CONFLICT(trade_date) DO UPDATE SET
        start_nav  = COALESCE(daily_summary.start_nav, excluded.start_nav),
        updated_at = excluded.updated_at
""")


class TradeService:
    """Records open trades from fills and closes them when exit fills arrive."""

    def __init__(self, db_session_factory: Any) -> None:
        self._db = db_session_factory

    async def open_trade(
        self,
        *,
        entry_order_id: str,
        strategy_id: str,
        symbol: str,
        side: str,
        quantity: Decimal,
        entry_price: Decimal,
        commission: Decimal,
        entry_at: datetime,
    ) -> None:
        trade_date = entry_at.astimezone(UTC).strftime("%Y-%m-%d")
        async with self._db() as db:
            await db.execute(_INSERT_TRADE, {
                "id": str(uuid4()),
                "strategy_id": strategy_id,
                "symbol": symbol,
                "side": side,
                "quantity": str(quantity),
                "entry_price": str(entry_price),
                "entry_at": entry_at.isoformat(),
                "commission": str(commission),
                "trade_date": trade_date,
                "entry_order_id": entry_order_id,
            })
            await db.commit()

    async def close_trade(
        self,
        *,
        entry_order_id: str,
        exit_order_id: str,
        exit_price: Decimal,
        commission: Decimal,
        exit_at: datetime,
    ) -> None:
        trade_date = exit_at.astimezone(UTC).strftime("%Y-%m-%d")
        async with self._db() as db:
            row = (await db.execute(_GET_OPEN_TRADE, {"entry_order_id": entry_order_id})).fetchone()
            if not row:
                return
            qty = Decimal(str(row.quantity))
            entry_price = Decimal(str(row.entry_price))
            total_commission = Decimal(str(row.commission)) + commission
            multiplier = Decimal("1") if row.side == "buy" else Decimal("-1")
            realised_pnl = multiplier * (exit_price - entry_price) * qty - total_commission

            await db.execute(_CLOSE_TRADE, {
                "exit_price": str(exit_price),
                "exit_at": exit_at.isoformat(),
                "realised_pnl": str(realised_pnl),
                "commission": str(total_commission),
                "exit_order_id": exit_order_id,
                "entry_order_id": entry_order_id,
            })
            await db.execute(_UPSERT_DAILY_SUMMARY, {
                "trade_date": trade_date,
                "updated_at": datetime.now(UTC).isoformat(),
            })
            await db.commit()

    async def record_nav(self, nav: Decimal, as_of: datetime) -> None:
        trade_date = as_of.astimezone(UTC).strftime("%Y-%m-%d")
        now = as_of.isoformat()
        async with self._db() as db:
            await db.execute(_ENSURE_DAILY_SUMMARY, {
                "trade_date": trade_date,
                "nav": str(nav),
                "updated_at": now,
            })
            await db.execute(_UPDATE_DAILY_NAV, {
                "trade_date": trade_date,
                "nav": str(nav),
                "updated_at": now,
            })
            await db.commit()
