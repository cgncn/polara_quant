"""BrokerAdapter — business logic layer for IB Gateway communication.

All ib_async interactions happen here. Nothing else in polara/ imports ib_async.
Float values from ib_async are converted to Decimal immediately upon receipt.
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
# Avoid hitting IB's reqAccountSummary rate limit (Error 322).
# NAV changes slowly; 5-minute cache is fresh enough for position sizing.
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


class BrokerDisconnectedError(RuntimeError):
    """Raised when an operation requires IB Gateway but it is not connected."""


class BrokerAdapter:
    """Business logic layer. Depends on IBClient; stores state in the DB."""

    def __init__(
        self,
        ib_client: IBClient,
        db_session_factory: Callable[[], Any],
    ) -> None:
        self._client = ib_client
        self._db_factory = db_session_factory
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._account_cache: tuple[datetime, AccountInfo] | None = None

    # ── connection status ──────────────────────────────────────────────────────

    async def get_broker_status(self) -> BrokerStatus:
        if not self._client.connected:
            return BrokerStatus(connected=False, ib_server_time=None, account_id=None)
        try:
            epoch = await self._client.ib.reqCurrentTimeAsync()
            server_time = datetime.fromtimestamp(epoch, tz=UTC)
        except Exception:  # noqa: BLE001
            server_time = None
        accounts = self._client.ib.managedAccounts()
        account_id = accounts[0] if accounts else None
        return BrokerStatus(
            connected=True,
            ib_server_time=server_time,
            account_id=account_id,
        )

    # ── account ────────────────────────────────────────────────────────────────

    async def get_account(self, *, force_refresh: bool = False) -> AccountInfo:
        """Return account info, using a short-lived cache to avoid IB Error 322.

        IB limits concurrent reqAccountSummary subscriptions per client ID.
        The cache (TTL=5 min) is fresh enough for position sizing and risk checks.
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
        summary = await self._client.ib.reqAccountSummaryAsync()
        values: dict[str, str] = {}
        currency = "USD"
        for av in summary:
            values[av.tag] = av.value
            if av.tag == "NetLiquidation":
                currency = av.currency
        account = AccountInfo(
            net_liquidation=Decimal(values.get("NetLiquidation", "0")),
            cash=Decimal(values.get("TotalCashValue", "0")),
            unrealised_pnl=Decimal(values.get("UnrealizedPnL", "0")),
            realised_pnl=Decimal(values.get("RealizedPnL", "0")),
            currency=currency,
            timestamp=now,
        )
        self._account_cache = (now, account)
        return account

    # ── positions ──────────────────────────────────────────────────────────────

    async def get_positions(self, db: AsyncSession | None = None) -> list[Position]:
        self._require_connected()
        ib_positions = self._client.ib.positions()
        result: list[Position] = []
        now = datetime.now(UTC)
        for p in ib_positions:
            qty = Decimal(str(p.position))
            avg = Decimal(str(p.avgCost))
            unrealised = Decimal(str(p.unrealPnl))
            result.append(
                Position(
                    symbol=p.contract.symbol,
                    quantity=qty,
                    avg_cost=avg,
                    unrealised_pnl=unrealised,
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
        """Submit order to IB and persist to DB. Returns order_id as string."""
        self._require_connected()
        from ib_async import LimitOrder, MarketOrder, Stock  # noqa: PLC0415

        contract = Stock(req.symbol, "SMART", "USD")
        action = req.side.upper()
        # ib_async constructors require float — this is the sole intentional IB API boundary
        # conversion. All internal representation stays Decimal. See CLAUDE.md Rule 1 exception.
        if req.limit_price is not None:
            order = LimitOrder(action, float(req.quantity), float(req.limit_price))
        else:
            order = MarketOrder(action, float(req.quantity))

        trade = self._client.ib.placeOrder(contract, order)
        ib_order_id: int | None = trade.order.orderId if trade else None

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
        """Submit a bracket order (parent market + stop child + take-profit child).

        IB requires transmit=False on all orders except the last child, which uses
        transmit=True to atomically submit the entire bracket.
        Returns the parent order_id as a string.
        """
        self._require_connected()
        from ib_async import LimitOrder, MarketOrder, Stock, StopOrder  # noqa: PLC0415

        contract = Stock(req.symbol, "SMART", "USD")
        action = req.side.upper()
        opposite = "SELL" if action == "BUY" else "BUY"
        qty = float(req.quantity)

        # Reserve parent order ID before creating children (they need parentId set).
        parent_id = self._client.ib.client.getReqId()

        parent = MarketOrder(action, qty, transmit=False)
        parent.orderId = parent_id

        # Build child orders; last one gets transmit=True.
        children: list[object] = []
        if stop_price is not None:
            stop = StopOrder(
                opposite, qty, float(stop_price), parentId=parent_id, transmit=False
            )
            children.append(stop)
        if take_profit_price is not None:
            tp = LimitOrder(
                opposite, qty, float(take_profit_price), parentId=parent_id, transmit=False
            )
            children.append(tp)

        if children:
            children[-1].transmit = True  # type: ignore[attr-defined]
        else:
            parent.transmit = True  # no children — transmit parent immediately

        parent_trade = self._client.ib.placeOrder(contract, parent)
        ib_order_id: int | None = parent_trade.order.orderId if parent_trade else None

        stop_ib_id: int | None = None
        tp_ib_id: int | None = None
        for i, child in enumerate(children):
            child_trade = self._client.ib.placeOrder(contract, child)
            child_ib_id = child_trade.order.orderId if child_trade else None
            if stop_price is not None and i == 0:
                stop_ib_id = child_ib_id
            else:
                tp_ib_id = child_ib_id

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
            req.order_id, ib_order_id, stop_price, take_profit_price,
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
            from ib_async import Order as IBOrder  # noqa: PLC0415
            cancel_order = IBOrder()
            cancel_order.orderId = row.ib_order_id
            self._client.ib.cancelOrder(cancel_order)

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

    # ── IB callbacks ───────────────────────────────────────────────────────────

    def _register_callbacks(self) -> None:
        """Attach ib_async event handlers for fills and order status changes.

        Must be called once after the IBClient is connected (i.e., from FastAPI lifespan).
        Calling before connection is established has no effect since callbacks only fire
        while the IB session is active.
        """
        self._client.ib.execDetailsEvent += self._on_exec_details
        self._client.ib.orderStatusEvent += self._on_order_status

    def _on_exec_details(self, trade: Any, fill: Any) -> None:
        """Fired when a fill execution arrives."""
        task = asyncio.create_task(self._save_fill(fill))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _save_fill(self, fill: Any) -> None:
        """Persist a fill from IB to the fills table."""
        try:
            exec_ = fill.execution
            comm = fill.commissionReport

            async with self._db_factory() as db:
                # Look up the application-layer order_id UUID from the ib_order_id integer
                order_row = (
                    await db.execute(
                        text("SELECT order_id FROM orders WHERE ib_order_id = :ib_oid"),
                        {"ib_oid": exec_.orderId},
                    )
                ).fetchone()

                if order_row is None:
                    logger.error(
                        "Cannot save fill: no order found for ib_order_id=%s (execId=%s)",
                        exec_.orderId,
                        exec_.execId,
                    )
                    return

                # Parse fill timestamp from IB execution object
                filled_at: str
                if hasattr(exec_, "time") and exec_.time:
                    filled_at = _parse_dt(str(exec_.time)).isoformat()
                else:
                    filled_at = datetime.now(UTC).isoformat()

                # ON CONFLICT (fill_id) DO NOTHING: PostgreSQL 9.5+ and SQLite 3.24+
                # portable syntax — not SQLite-specific.
                await db.execute(
                    text("""
                        INSERT INTO fills
                            (id, fill_id, order_id, symbol, side,
                             filled_quantity, fill_price, commission, filled_at)
                        VALUES
                            (:id, :fill_id, :order_id, :symbol, :side,
                             :filled_quantity, :fill_price, :commission, :filled_at)
                        ON CONFLICT (fill_id) DO NOTHING
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "fill_id": exec_.execId,
                        "order_id": order_row.order_id,
                        "symbol": fill.contract.symbol,
                        "side": "buy" if exec_.side == "BOT" else "sell",
                        "filled_quantity": str(Decimal(str(exec_.shares))),
                        "fill_price": str(Decimal(str(exec_.price))),
                        "commission": str(Decimal(str(comm.commission))) if comm else "0",
                        "filled_at": filled_at,
                    },
                )
                await db.execute(
                    text(
                        "UPDATE orders SET status = 'filled', filled_at = :now "
                        "WHERE ib_order_id = :ib_oid"
                    ),
                    {"now": datetime.now(UTC).isoformat(), "ib_oid": exec_.orderId},
                )
                await db.commit()
            logger.info("Fill saved: execId=%s", exec_.execId)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to save fill: %s", exc)

    def _on_order_status(self, trade: Any) -> None:
        """Fired when order status changes."""
        task = asyncio.create_task(self._update_order_status(trade))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _update_order_status(self, trade: Any) -> None:
        """Persist IB order status change to DB."""
        try:
            ib_status = trade.orderStatus.status
            status_map = {
                "Submitted": "submitted",
                "PreSubmitted": "submitted",
                "Filled": "filled",
                "Cancelled": "cancelled",
                "Inactive": "error",
            }
            our_status = status_map.get(ib_status)
            if our_status is None:
                return
            async with self._db_factory() as db:
                await db.execute(
                    text("UPDATE orders SET status = :status WHERE ib_order_id = :ib_oid"),
                    {"status": our_status, "ib_oid": trade.order.orderId},
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to update order status: %s", exc)

    # ── helpers ────────────────────────────────────────────────────────────────

    def _require_connected(self) -> None:
        if not self._client.connected:
            raise BrokerDisconnectedError("IB Gateway is not connected")


def _parse_dt(value: str) -> datetime:
    """Parse an ISO 8601 UTC string from DB into a UTC-aware datetime."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt
