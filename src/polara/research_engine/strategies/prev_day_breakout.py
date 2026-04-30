"""PrevDayBreakoutStrategy — breakout of previous session's high/low with volume confirmation.

Improvements:
  - ATR-based adaptive stop (atr_stop_multiplier × ATR / close) when atr_stop_multiplier is set
  - Falls back to fixed 1% stop when atr_stop_multiplier is None
  - volume_factor PARAM_GRID extended with 1.0 for more signals
All arithmetic in Decimal. Bar.volume is int — wrapped in Decimal() before arithmetic.
"""
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from polara.market_data.session import get_prev_session_bars, get_session_bars
from polara.research_engine.base import Strategy
from polara.research_engine.strategies.indicators import _compute_atr
from polara.schemas.market import Bar
from polara.schemas.signals import Signal

_ET = ZoneInfo("America/New_York")
_FIXED_STOP = Decimal("0.01")


@dataclass
class PrevDayBreakoutStrategy(Strategy):
    """Previous Day Breakout: signal when price exits the prior session range on elevated volume."""

    strategy_id: str
    symbol: str
    bar_size: str
    volume_factor: Decimal = Decimal("1.5")
    atr_period: int = 14
    atr_stop_multiplier: Decimal | None = None

    def __post_init__(self) -> None:
        self.PARAM_GRID = {
            "volume_factor": ["1.0", "1.2", "1.5", "2.0", "2.5"],
            "atr_stop_multiplier": ["1.5", "2.0", "2.5"],
        }

    @property
    def bars_needed(self) -> int:  # type: ignore[override]
        return max(40, self.atr_period + 2)

    def on_bars(self, bars: list[Bar]) -> Signal | None:
        if len(bars) < self.bars_needed:
            return None

        today = bars[-1].timestamp.astimezone(_ET).date()
        today_bars = get_session_bars(bars, today)
        if not today_bars:
            return None

        prev_bars = get_prev_session_bars(bars, today)
        if not prev_bars:
            return None

        prev_high = max(b.high for b in prev_bars)
        prev_low = min(b.low for b in prev_bars)

        avg_volume = sum(Decimal(b.volume) for b in prev_bars) / Decimal(len(prev_bars))

        last_bar = today_bars[-1]
        vol_threshold = avg_volume * self.volume_factor

        if avg_volume == Decimal("0"):
            volume_ok = False
        else:
            volume_ok = Decimal(last_bar.volume) > vol_threshold

        if last_bar.close > prev_high and volume_ok:
            strength = Decimal("1")
        elif last_bar.close < prev_low and volume_ok:
            strength = Decimal("-1")
        else:
            return None

        if self.atr_stop_multiplier is not None:
            atr = _compute_atr(bars, self.atr_period)
            if atr > Decimal("0") and last_bar.close > Decimal("0"):
                stop_loss_pct = atr * self.atr_stop_multiplier / last_bar.close
            else:
                stop_loss_pct = _FIXED_STOP
        else:
            stop_loss_pct = _FIXED_STOP

        return Signal(
            signal_id=uuid4(),
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            strength=strength,
            generated_at=datetime.now(UTC),
            reference_price=last_bar.close,
            stop_loss_pct=stop_loss_pct,
        )
