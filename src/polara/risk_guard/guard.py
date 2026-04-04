"""RiskGuard — pre-trade risk checks.

Checks:
1. Position size: current position notional / NAV <= max_position_pct
2. Daily loss: (unrealised_pnl + realised_pnl) / NAV >= -max_daily_loss_pct
   Once daily loss limit is breached, all checks raise until the next UTC day.
"""
import logging
from datetime import UTC, date, datetime
from decimal import Decimal

from polara.broker.schemas import AccountInfo, Position
from polara.risk_guard.exceptions import RiskViolationError
from polara.schemas.signals import Signal

logger = logging.getLogger(__name__)


class RiskGuard:
    """Pre-trade risk check engine."""

    def __init__(self, max_position_pct: Decimal, max_daily_loss_pct: Decimal) -> None:
        # Store as fractions (e.g. 10 -> 0.10)
        self._max_position = max_position_pct / Decimal(100)
        self._max_daily_loss = max_daily_loss_pct / Decimal(100)
        self._halted: bool = False
        self._halt_date: date | None = None

    @property
    def max_position_pct(self) -> Decimal:
        """Return the maximum position size as a percentage (e.g. 10 for 10%)."""
        return self._max_position * Decimal("100")

    def _reset_if_new_day(self) -> None:
        if self._halted and self._halt_date is not None:
            today = datetime.now(UTC).date()
            if today > self._halt_date:
                self._halted = False
                self._halt_date = None

    def _raise_if_halted(self) -> None:
        self._reset_if_new_day()
        if self._halted:
            raise RiskViolationError("Trading halted for the day due to daily loss limit breach")

    def check_position_size(
        self,
        signal: Signal,
        positions: list[Position],
        account: AccountInfo,
    ) -> None:
        """Raise RiskViolationError if current position in signal.symbol exceeds limit."""
        self._raise_if_halted()
        if account.net_liquidation == Decimal(0):
            return
        existing = next((p for p in positions if p.symbol == signal.symbol), None)
        if existing is None:
            return
        notional = abs(existing.quantity) * existing.avg_cost
        pct = notional / account.net_liquidation
        if pct > self._max_position:
            raise RiskViolationError(
                f"position size for {signal.symbol} is {pct:.1%} of NAV, "
                f"exceeds maximum {self._max_position:.1%}"
            )

    def check_daily_loss(self, account: AccountInfo) -> None:
        """Raise RiskViolationError if total P&L exceeds daily loss limit; halt trading."""
        self._raise_if_halted()
        if account.net_liquidation == Decimal(0):
            return
        total_pnl = account.unrealised_pnl + account.realised_pnl
        if total_pnl >= Decimal(0):
            return
        loss_pct = abs(total_pnl) / account.net_liquidation
        if loss_pct > self._max_daily_loss:
            self._halted = True
            self._halt_date = datetime.now(UTC).date()
            raise RiskViolationError(
                f"daily loss {loss_pct:.1%} exceeds maximum {self._max_daily_loss:.1%}. "
                f"Trading halted until next UTC day."
            )
