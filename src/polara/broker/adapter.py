"""BrokerAdapter — business logic layer for IBKR Client Portal REST API.

All REST interactions happen here via IBClient → CPClient. Nothing else imports CPClient.
Float values from the REST API are converted to Decimal immediately upon receipt.
"""
import asyncio
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from polara.broker.client import IBClient
from polara.broker.schemas import (
    AccountInfo,
    BrokerStatus,
    OrderStatus,
    OrderWithFills,
    PnLSnapshot,
    Position,
)
from polara.schemas.orders import Fill, OrderRequest

logger = logging.getLogger(__name__)

_PNL_SNAPSHOT_INTERVAL_SECONDS = 60
_ACCOUNT_CACHE_TTL_SECONDS = 300

_INSERT_ORDER = text("""
    INSERT INTO orders
        (id, order_id, symbol, side, quantity, limit_price, status,
         ib_order_id, strategy_id, submitted_at)
    VALUES
        (:id, :order_id, :symbol, :side, :quantity, :limit_price, :status,
         :ib_order_id, :strategy_id, :submitted_at)
""")

_INSERT_PNL_SNAPSHOT = text("""
    INSERT INTO account_snapshots
        (id, net_liquidation, cash, unrealised_pnl, realised_pnl, snapshot_at)
    VALUES
        (:id, :net_liquidation, :cash, :unrealised_pnl, :realised_pnl, :snapshot_at)
""")

_INSERT_BRACKET_ORDER = text("""
    INSERT INTO bracket_orders
        (id, order_id, stop_ib_id, take_profit_ib_id, stop_price, take_profit_price, created_at)
    VALUES
        (:id, :order_id, :stop_ib_id, :take_profit_ib_id,
         :stop_price, :take_profit_price, :created_at)
""")

# PostgreSQL 9.5+ and SQLite 3.24+ portable upsert syntax — not SQLite-specific.
_UPSERT_POSITION = text("""
    INSERT INTO positions (id, symbol, quantity, avg_cost, unrealised_pnl, updated_at)
    VALUES (:id, :symbol, :quantity, :avg_cost, :unrealised_pnl, :updated_at)
    ON CONFLICT (symbol) DO UPDATE SET
        quantity = excluded.quantity,
        avg_cost = excluded.avg_cost,
        unrealised_pnl = excluded.unrealised_pnl,
        updated_at = excluded.updated_at
""")

_STATUS_MAP = {
    "Submitted": "submitted",
    "PreSubmitted": "submitted",
    "Filled": "filled",
    "Cancelled": "cancelled",
    "Inactive": "error",
}


class BrokerDisconnectedError(RuntimeError):
    """Raised when an operation requires CP Gateway authentication but it is not available."""


class BrokerAdapter:
    """Business logic layer. Depends on IBClient; stores state in the DB."""

    def __init__(
        self,
        ib_client: IBClient,
        db_session_factory: Callable[[], Any],
        trade_service: Any | None = None,
    ) -> None:
        self._client = ib_client
        self._db_factory = db_session_factory
        self._trade_svc = trade_service
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._account_cache: tuple[datetime, AccountInfo] | None = None
        self._known_filled: set[int] = set()  # ib_order_ids already recorded as fills

    # ── connection status ──────────────────────────────────────────────────────

    async def get_broker_status(self) -> BrokerStatus:
        try:
            status = await self._client.cp.auth_status()
            account_id = self._client.cp._account_id
            return BrokerStatus(
                connected=bool(status.get("authenticated")),
                ib_server_time=datetime.now(UTC),
                account_id=account_id,
            )
        except Exception:
            return BrokerStatus(connected=False, ib_server_time=None, account_id=None)

    # ── account ────────────────────────────────────────────────────────────────

    async def get_account(self, *, force_refresh: bool = False) -> AccountInfo:
        """Return account info, using a short-lived cache to avoid hammering the REST API.

        Pass force_refresh=True to bypass the cache (e.g. for the PnL snapshot loop).
        """
        now = datetime.now(UTC)
        if (
            not force_refresh
            and self._account_cache is not None
            and (now - self._account_cache[0]).total_seconds() < _ACCOUNT_CACHE_TTL_SECONDS
        ):
            return self._account_cache[1]

        self._require_connected()
        summary = await self._client.cp.account_summary()

        def _d(key: str) -> Decimal:
            entry = summary.get(key, {})
            return Decimal(str(entry.get("amount", 0)))

        account = AccountInfo(
            net_liquidation=_d("netliquidation"),
            cash=_d("totalcashvalue"),
            unrealised_pnl=_d("unrealizedpnl"),
            realised_pnl=_d("realizedpnl"),
            currency="USD",
            timestamp=now,
        )
        self._account_cache = (now, account)
        return account

    # ── positions ──────────────────────────────────────────────────────────────

    async def get_positions(self, db: AsyncSession | None = None) -> list[Position]:
        self._require_connected()
        data = await self._client.cp.positions()
        result: list[Position] = []
        now = datetime.now(UTC)
        for p in data:
            qty = p.get("position", 0)
            if qty == 0:
                continue
            result.append(
                Position(
                    symbol=p.get("contractDesc", p.get("ticker", "")),
                    quantity=Decimal(str(qty)),
                    avg_cost=Decimal(str(p.get("avgCost", 0))),
                    unrealised_pnl=Decimal(str(p.get("unrealPnl", 0))),
                    updated_at=now,
                )
            )
        if db is not None:
            for pos in result:
                await db.execute(
                    _UPSERT_POSITION,
                    {
                        "id": str(uuid.uuid4()),
                        "symbol": pos.symbol,
                        "quantity": str(pos.quantity),
                        "avg_cost": str(pos.avg_cost),
                        "unrealised_pnl": str(pos.unrealised_pnl),
                        "updated_at": pos.updated_at.isoformat(),
                    },
                )
            await db.commit()
        return result

    # ── orders ─────────────────────────────────────────────────────────────────

    async def place_order(self, req: OrderRequest, db: AsyncSession) -> str:
        """Submit order via CP REST API and persist to DB. Returns order_id as string."""
        self._require_connected()
        conid = await self._client.cp.get_conid(req.symbol)
        payload: dict[str, Any] = {
            "conid": conid,
            "orderType": "LMT" if req.limit_price is not None else "MKT",
            "side": req.side.upper(),
            "quantity": float(req.quantity),
            "tif": "DAY",
            "acctId": self._client.cp.account_id,
        }
        if req.limit_price is not None:
            payload["price"] = float(req.limit_price)

        results = await self._client.cp.place_orders([payload])
        ib_order_id: int | None = None
        if results and "order_id" in results[0]:
            ib_order_id = int(results[0]["order_id"])

        now = datetime.now(UTC)
        await db.execute(
            _INSERT_ORDER,
            {
                "id": str(uuid.uuid4()),
                "order_id": str(req.order_id),
                "symbol": req.symbol,
                "side": req.side,
                "quantity": str(req.quantity),
                "limit_price": str(req.limit_price) if req.limit_price else None,
                "status": "submitted",
                "ib_order_id": ib_order_id,
                "strategy_id": req.strategy_id,
                "submitted_at": now.isoformat(),
            },
        )
        await db.commit()
        logger.info("Order %s submitted (ib_order_id=%s)", req.order_id, ib_order_id)
        return str(req.order_id)

    async def place_bracket_order(
        self,
        req: OrderRequest,
        stop_price: Decimal | None,
        take_profit_price: Decimal | None,
        db: AsyncSession,
    ) -> str:
        """Submit a bracket order via CP REST API (parent market + stop child + TP child).

        Uses cOID/parentId to link children to parent. Returns parent order_id.
        """
        self._require_connected()
        conid = await self._client.cp.get_conid(req.symbol)
        action = req.side.upper()
        opposite = "SELL" if action == "BUY" else "BUY"
        qty = float(req.quantity)
        parent_coid = str(uuid.uuid4())

        orders: list[dict[str, Any]] = [
            {
                "cOID": parent_coid,
                "conid": conid,
                "orderType": "MKT",
                "side": action,
                "quantity": qty,
                "tif": "DAY",
                "acctId": self._client.cp.account_id,
            }
        ]
        if stop_price is not None:
            orders.append(
                {
                    "parentId": parent_coid,
                    "conid": conid,
                    "orderType": "STP",
                    "side": opposite,
                    "auxPrice": float(stop_price),
                    "quantity": qty,
                    "tif": "GTC",
                    "acctId": self._client.cp.account_id,
                }
            )
        if take_profit_price is not None:
            orders.append(
                {
                    "parentId": parent_coid,
                    "conid": conid,
                    "orderType": "LMT",
                    "side": opposite,
                    "price": float(take_profit_price),
                    "quantity": qty,
                    "tif": "GTC",
                    "acctId": self._client.cp.account_id,
                }
            )

        results = await self._client.cp.place_orders(orders)
        ib_order_id: int | None = None
        stop_ib_id: int | None = None
        tp_ib_id: int | None = None
        if results:
            if "order_id" in results[0]:
                ib_order_id = int(results[0]["order_id"])
            if stop_price is not None and len(results) > 1 and "order_id" in results[1]:
                stop_ib_id = int(results[1]["order_id"])
            if take_profit_price is not None:
                idx = 2 if stop_price is not None else 1
                if len(results) > idx and "order_id" in results[idx]:
                    tp_ib_id = int(results[idx]["order_id"])

        now = datetime.now(UTC)
        await db.execute(
            _INSERT_ORDER,
            {
                "id": str(uuid.uuid4()),
                "order_id": str(req.order_id),
                "symbol": req.symbol,
                "side": req.side,
                "quantity": str(req.quantity),
                "limit_price": None,
                "status": "submitted",
                "ib_order_id": ib_order_id,
                "strategy_id": req.strategy_id,
                "submitted_at": now.isoformat(),
            },
        )
        await db.execute(
            _INSERT_BRACKET_ORDER,
            {
                "id": str(uuid.uuid4()),
                "order_id": str(req.order_id),
                "stop_ib_id": stop_ib_id,
                "take_profit_ib_id": tp_ib_id,
                "stop_price": str(stop_price) if stop_price is not None else None,
                "take_profit_price": (
                    str(take_profit_price) if take_profit_price is not None else None
                ),
                "created_at": now.isoformat(),
            },
        )
        await db.commit()
        logger.info(
            "Bracket order %s submitted (parent_ib_id=%s, stop=%s, tp=%s)",
            req.order_id,
            ib_order_id,
            stop_price,
            take_profit_price,
        )
        return str(req.order_id)

    async def cancel_order(self, order_id: str, db: AsyncSession) -> OrderStatus:
        """Cancel an open order by our order_id."""
        self._require_connected()

        row = (
            await db.execute(
                text("SELECT ib_order_id, status, submitted_at FROM orders WHERE order_id = :oid"),
                {"oid": order_id},
            )
        ).fetchone()

        if row is None:
            raise ValueError(f"Order {order_id} not found")
        if row.status in ("filled", "cancelled", "error"):
            raise ValueError(f"Cannot cancel order in status '{row.status}'")

        if row.ib_order_id is not None:
            await self._client.cp.cancel_order(int(row.ib_order_id))

        await db.execute(
            text("UPDATE orders SET status = 'cancelled' WHERE order_id = :oid"),
            {"oid": order_id},
        )
        await db.commit()

        return OrderStatus(
            order_id=uuid.UUID(order_id),
            ib_order_id=row.ib_order_id,
            status="cancelled",
            submitted_at=_parse_dt(row.submitted_at),
            filled_at=None,
        )

    async def list_orders(self, db: AsyncSession) -> list[OrderStatus]:
        rows = (
            await db.execute(
                text(
                    "SELECT order_id, ib_order_id, status, submitted_at, filled_at "
                    "FROM orders ORDER BY submitted_at DESC"
                )
            )
        ).fetchall()
        return [
            OrderStatus(
                order_id=uuid.UUID(row.order_id),
                ib_order_id=row.ib_order_id,
                status=row.status,
                submitted_at=_parse_dt(row.submitted_at),
                filled_at=_parse_dt(row.filled_at) if row.filled_at else None,
            )
            for row in rows
        ]

    async def get_order_with_fills(
        self, order_id: str, db: AsyncSession
    ) -> OrderWithFills | None:
        order_row = (
            await db.execute(
                text(
                    "SELECT order_id, ib_order_id, status, submitted_at, filled_at "
                    "FROM orders WHERE order_id = :oid"
                ),
                {"oid": order_id},
            )
        ).fetchone()
        if order_row is None:
            return None

        fill_rows = (
            await db.execute(
                text(
                    "SELECT fill_id, order_id, symbol, side, filled_quantity, "
                    "fill_price, commission, filled_at FROM fills WHERE order_id = :oid"
                ),
                {"oid": order_id},
            )
        ).fetchall()

        fills = [
            Fill(
                fill_id=uuid.UUID(r.fill_id),
                order_id=uuid.UUID(r.order_id),
                symbol=r.symbol,
                side=r.side,
                filled_quantity=Decimal(r.filled_quantity),
                fill_price=Decimal(r.fill_price),
                commission=Decimal(r.commission),
                filled_at=_parse_dt(r.filled_at),
            )
            for r in fill_rows
        ]

        return OrderWithFills(
            order_id=uuid.UUID(order_row.order_id),
            ib_order_id=order_row.ib_order_id,
            status=order_row.status,
            submitted_at=_parse_dt(order_row.submitted_at),
            filled_at=_parse_dt(order_row.filled_at) if order_row.filled_at else None,
            fills=fills,
        )

    # ── P&L ────────────────────────────────────────────────────────────────────

    async def get_pnl_snapshot(self) -> PnLSnapshot:
        """Fetch a fresh account snapshot, also refreshing the get_account cache."""
        account = await self.get_account(force_refresh=True)
        return PnLSnapshot(
            net_liquidation=account.net_liquidation,
            cash=account.cash,
            unrealised_pnl=account.unrealised_pnl,
            realised_pnl=account.realised_pnl,
            snapshot_at=account.timestamp,
        )

    async def pnl_snapshot_loop(self) -> None:
        """Background task: snapshot P&L to DB every 60 seconds."""
        while True:
            if self._client.connected:
                try:
                    snapshot = await self.get_pnl_snapshot()
                    async with self._db_factory() as db:
                        await db.execute(
                            _INSERT_PNL_SNAPSHOT,
                            {
                                "id": str(uuid.uuid4()),
                                "net_liquidation": str(snapshot.net_liquidation),
                                "cash": str(snapshot.cash),
                                "unrealised_pnl": str(snapshot.unrealised_pnl),
                                "realised_pnl": str(snapshot.realised_pnl),
                                "snapshot_at": snapshot.snapshot_at.isoformat(),
                            },
                        )
                        await db.commit()
                    logger.debug("P&L snapshot saved at %s", snapshot.snapshot_at)
                    if self._trade_svc is not None:
                        try:
                            await self._trade_svc.record_nav(
                                snapshot.net_liquidation, snapshot.snapshot_at
                            )
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("NAV record failed: %s", exc)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("P&L snapshot failed: %s", exc)
            await asyncio.sleep(_PNL_SNAPSHOT_INTERVAL_SECONDS)

    async def list_pnl_history(self, db: AsyncSession) -> list[PnLSnapshot]:
        rows = (
            await db.execute(
                text(
                    "SELECT net_liquidation, cash, unrealised_pnl, realised_pnl, snapshot_at "
                    "FROM account_snapshots ORDER BY snapshot_at DESC"
                )
            )
        ).fetchall()
        return [
            PnLSnapshot(
                net_liquidation=Decimal(r.net_liquidation),
                cash=Decimal(r.cash),
                unrealised_pnl=Decimal(r.unrealised_pnl),
                realised_pnl=Decimal(r.realised_pnl),
                snapshot_at=_parse_dt(r.snapshot_at),
            )
            for r in rows
        ]

    # ── order polling (replaces ib_async event callbacks) ─────────────────────

    def start_polling(self) -> asyncio.Task[None]:
        task = asyncio.create_task(self._order_polling_loop())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    async def _order_polling_loop(self) -> None:
        while True:
            await asyncio.sleep(5)
            if not self._client.connected:
                continue
            try:
                await self._sync_open_orders()
            except Exception as exc:  # noqa: BLE001
                logger.warning("order poll error: %s", exc)

    async def _sync_open_orders(self) -> None:
        resp = await self._client.cp.list_orders()
        orders_data = resp.get("orders") or []
        now = datetime.now(UTC)
        async with self._db_factory() as db:
            for o in orders_data:
                ib_id = o.get("orderId")
                raw_status = o.get("status", "")
                our_status = _STATUS_MAP.get(raw_status)
                if not ib_id or not our_status:
                    continue
                await db.execute(
                    text("UPDATE orders SET status = :status WHERE ib_order_id = :ib_oid"),
                    {"status": our_status, "ib_oid": int(ib_id)},
                )
                # Record trade open/close on new fills
                is_new_fill = our_status == "filled" and int(ib_id) not in self._known_filled
                if is_new_fill and self._trade_svc:
                    self._known_filled.add(int(ib_id))
                    try:
                        await self._record_fill(db, o, now)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("trade record failed for ib_id=%s: %s", ib_id, exc)
            await db.commit()

    async def _record_fill(self, db: Any, order_data: dict, filled_at: datetime) -> None:
        """Open or close a trade record when an IB order fills."""
        ib_id = int(order_data["orderId"])
        avg_price_raw = order_data.get("avgPrice") or order_data.get("price", "0")
        avg_price = Decimal(str(avg_price_raw))
        qty = Decimal(str(order_data.get("filledQuantity") or order_data.get("quantity", "0")))
        if avg_price <= 0 or qty <= 0:
            return

        # Look up our order record
        row = (await db.execute(
            text(
                "SELECT order_id, symbol, side, strategy_id"
                " FROM orders WHERE ib_order_id = :ib_id"
            ),
            {"ib_id": ib_id},
        )).fetchone()
        if not row:
            return

        order_id = row.order_id

        # Check if this is a bracket child (exit leg) by looking in bracket_orders
        bracket = (await db.execute(
            text(
                "SELECT order_id FROM bracket_orders "
                "WHERE stop_ib_id = :ib OR take_profit_ib_id = :ib"
            ),
            {"ib": ib_id},
        )).fetchone()

        if bracket:
            # Exit fill — close the trade opened by the parent order
            await self._trade_svc.close_trade(
                entry_order_id=bracket.order_id,
                exit_order_id=order_id,
                exit_price=avg_price,
                commission=Decimal("1"),
                exit_at=filled_at,
            )
        else:
            # Entry fill — open a new trade
            await self._trade_svc.open_trade(
                entry_order_id=order_id,
                strategy_id=row.strategy_id,
                symbol=row.symbol,
                side=row.side,
                quantity=qty,
                entry_price=avg_price,
                commission=Decimal("1"),
                entry_at=filled_at,
            )

    # ── helpers ────────────────────────────────────────────────────────────────

    def _require_connected(self) -> None:
        if not self._client.connected:
            raise BrokerDisconnectedError(
                "IBKR Client Portal Gateway is not authenticated. "
                "Visit https://<cp-gateway-host>:5000 to log in."
            )


def _parse_dt(value: str) -> datetime:
    """Parse an ISO 8601 UTC string from DB into a UTC-aware datetime."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt
