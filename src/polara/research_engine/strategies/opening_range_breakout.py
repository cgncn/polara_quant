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

        if last_bar.close > range_high and prev_session_bar.close <= range_high:
            strength = Decimal("1")
            stop_loss_pct = (last_bar.close - range_low) / last_bar.close + self.stop_buffer_pct
            assert stop_loss_pct > 0
        elif last_bar.close < range_low and prev_session_bar.close >= range_low:
            strength = Decimal("-1")
            stop_loss_pct = (range_high - last_bar.close) / last_bar.close + self.stop_buffer_pct
            assert stop_loss_pct > 0
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
