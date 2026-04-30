"""SupertrendStrategy — ATR-based trend-following with band-flip signals.

Basic bands per bar:
  upper_basic = (high + low) / 2 + multiplier × ATR(atr_period)
  lower_basic = (high + low) / 2 − multiplier × ATR(atr_period)

Final bands ratchet with the trend (only narrow, never widen, in trend direction):
  upper = min(upper_basic, upper_prev) if prev_close ≤ upper_prev else upper_basic
  lower = max(lower_basic, lower_prev) if prev_close ≥ lower_prev else lower_basic

Direction: 1 (uptrend) if close > upper, -1 (downtrend) if close < lower, else unchanged.
Signal: fires only when direction flips between the last two bars.
All arithmetic in Decimal.
"""
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from polara.research_engine.base import Strategy
from polara.research_engine.strategies.indicators import _compute_atr
from polara.schemas.market import Bar
from polara.schemas.signals import Signal


@dataclass
class SupertrendStrategy(Strategy):
    """ATR Supertrend: buy on uptrend flip, sell on downtrend flip."""

    strategy_id: str
    symbol: str
    bar_size: str
    atr_period: int = 10
    multiplier: Decimal = Decimal("3.0")
    stop_loss_pct: Decimal | None = None
    take_profit_pct: Decimal | None = None

    def __post_init__(self) -> None:
        self.PARAM_GRID = {
            "atr_period": [7, 10, 14],
            "multiplier": ["2.0", "3.0", "4.0"],
        }

    @property
    def bars_needed(self) -> int:  # type: ignore[override]
        # ATR needs atr_period+1 bars; plus 1 prior bar for direction flip detection
        return self.atr_period + 2

    def on_bars(self, bars: list[Bar]) -> Signal | None:
        """Return Signal if Supertrend direction flipped on the last bar, else None."""
        if len(bars) < self.bars_needed:
            return None

        window = bars[-(self.atr_period + 2):]

        atr = _compute_atr(window, self.atr_period)
        if atr == Decimal("0"):
            return None

        prev = window[-2]
        curr = window[-1]

        def _basic_bands(bar: Bar) -> tuple[Decimal, Decimal]:
            mid = (bar.high + bar.low) / Decimal("2")
            offset = self.multiplier * atr
            return mid + offset, mid - offset

        upper_prev_basic, lower_prev_basic = _basic_bands(prev)
        upper_curr_basic, lower_curr_basic = _basic_bands(curr)

        prev_close = prev.close
        curr_close = curr.close

        upper_prev = upper_prev_basic
        lower_prev = lower_prev_basic

        upper_curr = (
            min(upper_curr_basic, upper_prev)
            if prev_close <= upper_prev
            else upper_curr_basic
        )
        lower_curr = (
            max(lower_curr_basic, lower_prev)
            if prev_close >= lower_prev
            else lower_curr_basic
        )

        # Determine direction at previous bar from basic bands (seed state)
        if prev_close > upper_prev:
            dir_prev = Decimal("1")
        elif prev_close < lower_prev:
            dir_prev = Decimal("-1")
        else:
            return None  # Previous bar is indeterminate — can't confirm a flip

        # Determine direction at current bar
        if curr_close > upper_curr:
            dir_curr = Decimal("1")
        elif curr_close < lower_curr:
            dir_curr = Decimal("-1")
        else:
            dir_curr = dir_prev  # Inside bands — trend continues

        if dir_curr == dir_prev:
            return None

        return Signal(
            signal_id=uuid4(),
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            strength=dir_curr,
            generated_at=datetime.now(UTC),
            reference_price=bars[-1].close,
            stop_loss_pct=self.stop_loss_pct,
            take_profit_pct=self.take_profit_pct,
        )
