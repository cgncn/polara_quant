"""MomentumStrategy — Rate-of-Change (ROC) price momentum.

ROC = (close[t] − close[t − period]) / close[t − period] × 100

Buy when ROC crosses above +threshold (positive momentum breakout).
Sell when ROC crosses below −threshold (negative momentum breakout).
All arithmetic in Decimal.
"""
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from polara.research_engine.base import Strategy
from polara.schemas.market import Bar
from polara.schemas.signals import Signal


def _roc(closes: list[Decimal], period: int, offset: int = 0) -> Decimal:
    """Rate of change as a percentage at `offset` bars before the last bar."""
    end = len(closes) - offset
    current = closes[end - 1]
    prior = closes[end - 1 - period]
    if prior == Decimal("0"):
        return Decimal("0")
    return (current - prior) / prior * Decimal("100")


@dataclass
class MomentumStrategy(Strategy):
    """ROC Momentum: buy when ROC crosses above threshold, sell when it crosses below −threshold."""

    strategy_id: str
    symbol: str
    period: int
    threshold: Decimal   # Percentage, e.g. Decimal("2") = 2%
    quantity: Decimal
    bar_size: str
    stop_loss_pct: Decimal | None = None
    take_profit_pct: Decimal | None = None

    @property
    def bars_needed(self) -> int:  # type: ignore[override]
        # Need period + current bar + 1 previous bar for crossover detection
        return self.period + 2

    def on_bars(self, bars: list[Bar]) -> Signal | None:
        """Return Signal if ROC crossed the threshold on the last bar, else None."""
        if len(bars) < self.bars_needed:
            return None

        closes = [b.close for b in bars]
        roc_now = _roc(closes, self.period, offset=0)
        roc_prev = _roc(closes, self.period, offset=1)

        if roc_prev <= self.threshold and roc_now > self.threshold:
            strength = Decimal("1")
        elif roc_prev >= -self.threshold and roc_now < -self.threshold:
            strength = Decimal("-1")
        else:
            return None

        return Signal(
            signal_id=uuid4(),
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            strength=strength,
            generated_at=datetime.now(UTC),
            reference_price=bars[-1].close,
            stop_loss_pct=self.stop_loss_pct,
            take_profit_pct=self.take_profit_pct,
        )
