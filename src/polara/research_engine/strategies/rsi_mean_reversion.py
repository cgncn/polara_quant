"""RSIMeanReversionStrategy — RSI-based mean reversion signal generator.

Uses Wilder's EMA for RSI calculation. All arithmetic in Decimal.
Buy when RSI recovers back above the oversold threshold (crossover confirmation).
Sell when RSI falls back below the overbought threshold (crossover confirmation).
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

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    gains = [d if d > Decimal(0) else Decimal(0) for d in deltas]
    losses = [abs(d) if d < Decimal(0) else Decimal(0) for d in deltas]

    avg_gain = sum(gains[:period], Decimal(0)) / period_d
    avg_loss = sum(losses[:period], Decimal(0)) / period_d

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * Decimal(period - 1) + gains[i]) / period_d
        avg_loss = (avg_loss * Decimal(period - 1) + losses[i]) / period_d

    if avg_loss == Decimal(0):
        return Decimal("100")

    rs = avg_gain / avg_loss
    return Decimal("100") - (Decimal("100") / (Decimal("1") + rs))


@dataclass
class RSIMeanReversionStrategy(Strategy):
    """RSI mean-reversion: buy on recovery from oversold, sell on recovery from overbought."""

    strategy_id: str
    symbol: str
    period: int = 14
    oversold: Decimal = Decimal("30")
    overbought: Decimal = Decimal("70")
    quantity: Decimal = Decimal("1")
    bar_size: str = "5 mins"
    stop_loss_pct: Decimal | None = None
    take_profit_pct: Decimal | None = None

    def __post_init__(self) -> None:
        self.PARAM_GRID = {
            "period": [9, 14, 21],
            "oversold": ["25", "30", "35"],
            "overbought": ["65", "70", "75"],
        }

    @property
    def bars_needed(self) -> int:  # type: ignore[override]
        # Need two consecutive RSI values: each requires period+1 bars,
        # so the full window is period+2.
        return self.period + 2

    def on_bars(self, bars: list[Bar]) -> Signal | None:
        """Return buy on RSI recovery above oversold, sell on pullback below overbought."""
        if len(bars) < self.bars_needed:
            return None

        rsi_now = _compute_rsi(bars, self.period)
        rsi_prev = _compute_rsi(bars[:-1], self.period)

        if rsi_prev < self.oversold and rsi_now >= self.oversold:
            strength = Decimal("1")
        elif rsi_prev > self.overbought and rsi_now <= self.overbought:
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
