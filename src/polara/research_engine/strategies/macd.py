"""MACDStrategy — MACD signal-line crossover.

MACD line = EMA(fast) − EMA(slow)
Signal line = EMA(signal_period) of MACD line
Buy when MACD crosses above signal; sell when it crosses below.
All arithmetic in Decimal.
"""
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from polara.research_engine.base import Strategy
from polara.schemas.market import Bar
from polara.schemas.signals import Signal


def _ema(values: list[Decimal], period: int) -> list[Decimal]:
    """Compute the full EMA series for the given values and period.

    Uses SMA of the first `period` values as the seed, then applies Wilder's
    multiplier k = 2 / (period + 1) for subsequent values.
    Returns a list of the same length as values, with the first (period - 1)
    elements set to the seed EMA value so callers always get a full-length series.
    """
    if len(values) < period:
        return []
    k = Decimal(2) / Decimal(period + 1)
    seed = sum(values[:period], Decimal(0)) / Decimal(period)
    result: list[Decimal] = [seed] * period
    for v in values[period:]:
        result.append(result[-1] + k * (v - result[-1]))
    return result


@dataclass
class MACDStrategy(Strategy):
    """MACD crossover: buy when MACD crosses above signal line, sell when it crosses below."""

    strategy_id: str
    symbol: str
    fast_period: int
    slow_period: int
    signal_period: int
    quantity: Decimal
    bar_size: str
    stop_loss_pct: Decimal | None = None
    take_profit_pct: Decimal | None = None

    def __post_init__(self) -> None:
        self.PARAM_GRID = {
            "fast_period": [8, 12, 16],
            "slow_period": [21, 26, 34],
            "signal_period": [7, 9, 12],
        }

    @property
    def bars_needed(self) -> int:  # type: ignore[override]
        # Need slow_period bars for first slow EMA seed, plus signal_period bars
        # of MACD history for the signal EMA seed, plus 1 previous bar for crossover.
        return self.slow_period + self.signal_period + 1

    def on_bars(self, bars: list[Bar]) -> Signal | None:
        """Return Signal if MACD crossed signal line on the last bar, else None."""
        if len(bars) < self.bars_needed:
            return None

        closes = [b.close for b in bars]

        fast_ema = _ema(closes, self.fast_period)
        slow_ema = _ema(closes, self.slow_period)
        if not fast_ema or not slow_ema:
            return None

        # Align MACD line to slow_ema length (slow EMA is the shorter series)
        offset = len(fast_ema) - len(slow_ema)
        macd_line = [fast_ema[i + offset] - slow_ema[i] for i in range(len(slow_ema))]

        signal_line = _ema(macd_line, self.signal_period)
        if len(signal_line) < 2:
            return None

        macd_now = macd_line[-1]
        macd_prev = macd_line[-2]
        sig_now = signal_line[-1]
        sig_prev = signal_line[-2]

        if macd_prev <= sig_prev and macd_now > sig_now:
            strength = Decimal("1")
        elif macd_prev >= sig_prev and macd_now < sig_now:
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
