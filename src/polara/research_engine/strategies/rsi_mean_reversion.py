"""RSIMeanReversionStrategy — RSI-based mean reversion signal generator.

Uses Wilder's EMA for RSI calculation. All arithmetic in Decimal.
Buy when RSI < oversold threshold, sell when RSI > overbought threshold.
"""
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from polara.research_engine.base import Strategy
from polara.schemas.market import Bar
from polara.schemas.signals import Signal


def _compute_rsi(bars: list[Bar], period: int) -> Decimal:
    """Compute RSI using Wilder's smoothed moving average.

    Requires len(bars) >= period + 1 (period deltas needed).
    Returns Decimal in [0, 100].
    """
    period_d = Decimal(period)
    closes = [b.close for b in bars]

    # Compute price changes
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    gains = [d if d > Decimal(0) else Decimal(0) for d in deltas]
    losses = [abs(d) if d < Decimal(0) else Decimal(0) for d in deltas]

    # Initial average using first `period` deltas
    avg_gain = sum(gains[:period], Decimal(0)) / period_d
    avg_loss = sum(losses[:period], Decimal(0)) / period_d

    # Wilder's EMA for remaining deltas
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * Decimal(period - 1) + gains[i]) / period_d
        avg_loss = (avg_loss * Decimal(period - 1) + losses[i]) / period_d

    if avg_loss == Decimal(0):
        return Decimal("100")

    rs = avg_gain / avg_loss
    return Decimal("100") - (Decimal("100") / (Decimal("1") + rs))


@dataclass
class RSIMeanReversionStrategy(Strategy):
    """RSI mean-reversion: buy when oversold, sell when overbought."""

    strategy_id: str
    symbol: str
    period: int = 14
    oversold: Decimal = Decimal("30")
    overbought: Decimal = Decimal("70")
    quantity: Decimal = Decimal("1")
    bar_size: str = "5 mins"

    @property
    def bars_needed(self) -> int:  # type: ignore[override]
        return self.period + 1  # need period+1 closes for period deltas

    def on_bars(self, bars: list[Bar]) -> Signal | None:
        """Return buy signal if RSI < oversold, sell if RSI > overbought, else None."""
        if len(bars) < self.bars_needed:
            return None

        rsi = _compute_rsi(bars, self.period)

        if rsi < self.oversold:
            strength = Decimal("1")
        elif rsi > self.overbought:
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
        )
