"""OrderManager — links signals to order submissions via RiskGuard + BrokerAdapter."""
import logging
from datetime import UTC, datetime
from decimal import ROUND_DOWN, ROUND_UP, Decimal
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
    " (id, signal_id, order_id, strategy_id, symbol, signal_strength,"
    "  stop_price, take_profit_price, created_at)"
    " VALUES (:id, :signal_id, :order_id, :strategy_id, :symbol, :signal_strength,"
    "  :stop_price, :take_profit_price, :created_at)"
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
        self._pending: dict[str, Decimal] = {}

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

    def _reconcile_pending(self, positions: list) -> None:
        """Clear pending entries for symbols where held quantity >= pending quantity.

        Call after fetching live positions to remove entries for filled orders.
        """
        held_by_symbol = {p.symbol: p.quantity for p in positions}
        for symbol in list(self._pending):
            held = held_by_symbol.get(symbol, Decimal("0"))
            if held >= self._pending[symbol]:
                del self._pending[symbol]

    def _compute_delta(
        self, symbol: str, quantity_target: Decimal, positions: list
    ) -> Decimal:
        """Compute quantity still needed to reach target, accounting for in-flight orders.

        delta = max(0, target - held - in_flight)
        """
        held_by_symbol = {p.symbol: p.quantity for p in positions}
        current_held = held_by_symbol.get(symbol, Decimal("0"))
        in_flight = self._pending.get(symbol, Decimal("0"))
        return max(Decimal("0"), quantity_target - current_held - in_flight)

    def _compute_exit_prices(
        self, signal: Signal, side: str
    ) -> tuple[Decimal | None, Decimal | None]:
        """Convert percentage stop/take-profit params to absolute prices.

        For buys:  stop  = price × (1 - pct/100), rounded down to nearest cent
                   tp    = price × (1 + pct/100), rounded up to nearest cent
        For sells: stop  = price × (1 + pct/100), rounded up   (stop above entry)
                   tp    = price × (1 - pct/100), rounded down (profit below entry)

        Returns (None, None) if reference_price is not set on the signal.
        """
        if signal.reference_price is None:
            return None, None

        price = signal.reference_price
        stop: Decimal | None = None
        take_profit: Decimal | None = None

        if side == "buy":
            if signal.stop_loss_pct:
                stop = (price * (1 - signal.stop_loss_pct / Decimal("100"))).quantize(
                    Decimal("0.01"), rounding=ROUND_DOWN
                )
            if signal.take_profit_pct:
                take_profit = (
                    price * (1 + signal.take_profit_pct / Decimal("100"))
                ).quantize(Decimal("0.01"), rounding=ROUND_UP)
        else:  # sell / short
            if signal.stop_loss_pct:
                stop = (price * (1 + signal.stop_loss_pct / Decimal("100"))).quantize(
                    Decimal("0.01"), rounding=ROUND_UP
                )
            if signal.take_profit_pct:
                take_profit = (
                    price * (1 - signal.take_profit_pct / Decimal("100"))
                ).quantize(Decimal("0.01"), rounding=ROUND_DOWN)

        return stop, take_profit

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
            self._reconcile_pending(positions)
            self._risk_guard.check_daily_loss(account)
            self._risk_guard.check_position_size(signal, positions, account)
        except RiskViolationError as e:
            logger.warning("Risk violation for signal %s: %s", signal.signal_id, e)
            return None

        quantity_target = self._compute_quantity(signal, account)
        if quantity_target is None:
            return None

        delta = self._compute_delta(signal.symbol, quantity_target, positions)
        if delta < self._min_order_quantity:
            logger.info(
                "Delta %s for %s is below minimum %s — skipping signal",
                delta, signal.symbol, self._min_order_quantity,
            )
            return None

        side = "buy" if signal.strength > Decimal(0) else "sell"
        stop_price, take_profit_price = self._compute_exit_prices(signal, side)

        req = OrderRequest(
            order_id=uuid4(),
            symbol=signal.symbol,
            side=side,
            quantity=delta,
            limit_price=None,
            requested_at=datetime.now(UTC),
            strategy_id=signal.strategy_id,
        )

        async with self._db() as db:
            if stop_price is not None or take_profit_price is not None:
                order_status = await self._adapter.place_bracket_order(
                    req, stop_price, take_profit_price, db
                )
            else:
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
                    "stop_price": str(stop_price) if stop_price is not None else None,
                    "take_profit_price": (
                        str(take_profit_price) if take_profit_price is not None else None
                    ),
                    "created_at": datetime.now(UTC).isoformat(),
                },
            )
            await db.commit()

        self._pending[signal.symbol] = (
            self._pending.get(signal.symbol, Decimal("0")) + delta
        )
        return order_status
