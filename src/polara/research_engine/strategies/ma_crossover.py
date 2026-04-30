"""MACrossoverStrategy — simple moving average crossover signal generator.

Uses Decimal arithmetic throughout (no float for price calculations).
signal.strength = +1 on fast-crosses-above, -1 on fast-crosses-below.
"""
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from polara.research_engine.base import Strategy
from polara.schemas.market import Bar
from polara.schemas.signals import Signal


def _sma(values: list[Decimal], period: int, offset: int = 0) -> Decimal:
    """Simple moving average of `period` values ending at `offset` from the end.

    offset=0: use the last `period` values (current bar)
    offset=1: use the second-to-last `period` values (previous bar)
    """
    end = len(values) - offset
    window = values[end - period : end]
    return sum(window, Decimal(0)) / Decimal(period)


@dataclass
class MACrossoverStrategy(Strategy):
    """MA crossover: buy when fast MA crosses above slow MA, sell when it crosses below."""

    strategy_id: str
    symbol: str
    fast_period: int
    slow_period: int
    quantity: Decimal
    bar_size: str
    stop_loss_pct: Decimal | None = None
    take_profit_pct: Decimal | None = None

    def __post_init__(self) -> None:
        self.PARAM_GRID = {
            "fast_period": [5, 9, 12],
            "slow_period": [20, 26, 50],
        }

    @property
    def bars_needed(self) -> int:  # type: ignore[override]
        return self.slow_period + 1  # +1 to compute previous-bar MAs

    def on_bars(self, bars: list[Bar]) -> Signal | None:
        """Return Signal if fast MA crossed slow MA on the last bar, else None."""
        if len(bars) < self.bars_needed:
            return None

        closes = [b.close for b in bars]

        fast_now = _sma(closes, self.fast_period, offset=0)
        slow_now = _sma(closes, self.slow_period, offset=0)
        fast_prev = _sma(closes, self.fast_period, offset=1)
        slow_prev = _sma(closes, self.slow_period, offset=1)

        if fast_prev <= slow_prev and fast_now > slow_now:
            strength = Decimal("1")
        elif fast_prev >= slow_prev and fast_now < slow_now:
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
