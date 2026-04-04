"""OrderManager — links signals to order submissions via RiskGuard + BrokerAdapter."""
import logging
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from uuid import uuid4

from sqlalchemy import text

from polara.broker.adapter import BrokerAdapter
from polara.broker.schemas import OrderStatus
from polara.research_engine.status_service import StrategyStatusService
from polara.risk_guard.exceptions import RiskViolationError
from polara.risk_guard.guard import RiskGuard
from polara.schemas.orders import OrderRequest
from polara.schemas.signals import Signal

logger = logging.getLogger(__name__)

_INSERT_SIGNAL_ORDER = text(
    "INSERT INTO signal_orders"
    " (id, signal_id, order_id, strategy_id, symbol, signal_strength, created_at)"
    " VALUES (:id, :signal_id, :order_id, :strategy_id, :symbol, :signal_strength, :created_at)"
)


class OrderManager:
    """Processes signals: runs risk checks then submits orders via BrokerAdapter."""

    def __init__(
        self,
        broker_adapter: BrokerAdapter,
        risk_guard: RiskGuard,
        db_session_factory,
        status_service: StrategyStatusService,
        min_order_quantity: Decimal = Decimal("1"),
    ) -> None:
        self._adapter = broker_adapter
        self._risk_guard = risk_guard
        self._db = db_session_factory
        self._status_service = status_service
        self._min_order_quantity = min_order_quantity

    def _compute_quantity(self, signal: Signal, account) -> Decimal | None:
        """Compute order quantity from signal strength and account NAV.

        Returns None if computed quantity is below minimum (signal should be skipped).
        Falls back to quantity=1 if signal has no reference_price.
        """
        if signal.reference_price and signal.reference_price > Decimal(0):
            target_notional = (
                account.net_liquidation
                * (self._risk_guard.max_position_pct / Decimal("100"))
                * abs(signal.strength)
            )
            quantity = (target_notional / signal.reference_price).to_integral_value(
                rounding=ROUND_DOWN
            )
        else:
            logger.warning(
                "Signal for %s has no reference_price — falling back to quantity=1",
                signal.symbol,
            )
            quantity = Decimal("1")

        if quantity < self._min_order_quantity:
            logger.info(
                "Computed quantity %s for %s is below minimum %s — skipping signal",
                quantity,
                signal.symbol,
                self._min_order_quantity,
            )
            return None

        return quantity

    async def process_signal(self, signal: Signal) -> OrderStatus | None:
        """Run risk checks and submit order.

        Returns None if strategy is not live or risk check fails.
        """
        status = await self._status_service.get_status(signal.strategy_id)
        if status != "live":
            logger.info(
                "Signal from strategy %s skipped — status is %r (not live)",
                signal.strategy_id,
                status,
            )
            return None

        try:
            account = await self._adapter.get_account()
            positions = await self._adapter.get_positions()
            self._risk_guard.check_daily_loss(account)
            self._risk_guard.check_position_size(signal, positions, account)
        except RiskViolationError as e:
            logger.warning("Risk violation for signal %s: %s", signal.signal_id, e)
            return None

        quantity = self._compute_quantity(signal, account)
        if quantity is None:
            return None

        side = "buy" if signal.strength > Decimal(0) else "sell"
        req = OrderRequest(
            order_id=uuid4(),
            symbol=signal.symbol,
            side=side,
            quantity=quantity,
            limit_price=None,
            requested_at=datetime.now(UTC),
            strategy_id=signal.strategy_id,
        )

        async with self._db() as db:
            order_status = await self._adapter.place_order(req, db)
            await db.execute(
                _INSERT_SIGNAL_ORDER,
                {
                    "id": str(uuid4()),
                    "signal_id": str(signal.signal_id),
                    "order_id": str(req.order_id),
                    "strategy_id": signal.strategy_id,
                    "symbol": signal.symbol,
                    "signal_strength": str(signal.strength),
                    "created_at": datetime.now(UTC).isoformat(),
                },
            )
            await db.commit()

        return order_status
