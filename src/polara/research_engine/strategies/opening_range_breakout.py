"""OpeningRangeBreakoutStrategy — breakout of the first N bars' high/low.

Improvements:
  - Volume confirmation: breakout bar volume must exceed opening-range avg × volume_factor
  - Min range filter: opening range height must be >= min_range_pct of price (avoids choppy opens)
  - No assert statements — returns None on guard failures
All arithmetic in Decimal.
"""
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from polara.market_data.session import get_session_bars, opening_range_end_utc
from polara.research_engine.base import Strategy
from polara.schemas.market import Bar
from polara.schemas.signals import Signal

_ET = ZoneInfo("America/New_York")


@dataclass
class OpeningRangeBreakoutStrategy(Strategy):
    """Opening Range Breakout: signal when price crosses the high/low of the opening range."""

    strategy_id: str
    symbol: str
    bar_size: str
    opening_bars: int = 2
    stop_buffer_pct: Decimal = Decimal("0.001")
    volume_factor: Decimal = Decimal("1.2")
    min_range_pct: Decimal = Decimal("0.002")

    def __post_init__(self) -> None:
        self.PARAM_GRID = {
            "opening_bars": [1, 2, 3],
            "stop_buffer_pct": ["0.001", "0.002", "0.003"],
            "volume_factor": ["1.0", "1.2", "1.5", "2.0"],
            "min_range_pct": ["0.001", "0.002", "0.003"],
        }

    @property
    def bars_needed(self) -> int:  # type: ignore[override]
        return self.opening_bars + 1

    def on_bars(self, bars: list[Bar]) -> Signal | None:
        if not bars:
            return None
        today = bars[-1].timestamp.astimezone(_ET).date()
        session_bars = get_session_bars(bars, today)

        if len(session_bars) < self.opening_bars + 1:
            return None

        or_end = opening_range_end_utc(today, self.bar_size, self.opening_bars)
        opening_range_bars = [b for b in session_bars if b.timestamp < or_end]

        if len(opening_range_bars) < self.opening_bars:
            return None

        range_high = max(b.high for b in opening_range_bars)
        range_low = min(b.low for b in opening_range_bars)

        last_bar = session_bars[-1]
        prev_session_bar = session_bars[-2]

        # Min range filter: skip choppy opens where range is too tight
        if last_bar.close > Decimal("0"):
            range_height_pct = (range_high - range_low) / last_bar.close
            if range_height_pct < self.min_range_pct:
                return None

        # Volume confirmation: last bar volume vs opening range average
        avg_or_volume = sum(Decimal(b.volume) for b in opening_range_bars) / Decimal(
            len(opening_range_bars)
        )
        if avg_or_volume > Decimal("0"):
            volume_ok = Decimal(last_bar.volume) >= avg_or_volume * self.volume_factor
        else:
            volume_ok = True  # no volume data → allow signal

        if last_bar.close > range_high and prev_session_bar.close <= range_high:
            if not volume_ok:
                return None
            strength = Decimal("1")
            stop_loss_pct = (last_bar.close - range_low) / last_bar.close + self.stop_buffer_pct
            if stop_loss_pct <= Decimal("0"):
                return None
        elif last_bar.close < range_low and prev_session_bar.close >= range_low:
            if not volume_ok:
                return None
            strength = Decimal("-1")
            stop_loss_pct = (range_high - last_bar.close) / last_bar.close + self.stop_buffer_pct
            if stop_loss_pct <= Decimal("0"):
                return None
        else:
            return None

        return Signal(
            signal_id=uuid4(),
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            strength=strength,
            generated_at=datetime.now(UTC),
            reference_price=last_bar.close,
            stop_loss_pct=stop_loss_pct,
        )
