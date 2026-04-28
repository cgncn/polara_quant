from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from polara.market_data.session import get_prev_session_bars, get_session_bars
from polara.research_engine.base import Strategy
from polara.schemas.market import Bar
from polara.schemas.signals import Signal


@dataclass
class GapFillStrategy(Strategy):
    """Fade overnight gaps: sell gap-ups, buy gap-downs, targeting gap closure."""

    strategy_id: str
    symbol: str
    bar_size: str
    min_gap_pct: Decimal = Decimal("0.005")

    @property
    def bars_needed(self) -> int:  # type: ignore[override]
        return 20

    def on_bars(self, bars: list[Bar]) -> Signal | None:
        if len(bars) < self.bars_needed:
            return None

        today = bars[-1].timestamp.astimezone(ZoneInfo("America/New_York")).date()
        today_bars = get_session_bars(bars, today)

        if len(today_bars) != 1:
            return None

        prev_bars = get_prev_session_bars(bars, today)
        if len(prev_bars) == 0:
            return None

        prev_close = prev_bars[-1].close
        today_open = today_bars[0].open
        gap = (today_open - prev_close) / prev_close

        if gap > self.min_gap_pct:
            strength = Decimal("-1")
            take_profit_pct = gap - self.min_gap_pct
        elif gap < -self.min_gap_pct:
            strength = Decimal("1")
            take_profit_pct = abs(gap) - self.min_gap_pct
        else:
            return None

        stop_loss_pct = self.min_gap_pct

        return Signal(
            signal_id=uuid4(),
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            strength=strength,
            generated_at=datetime.now(UTC),
            reference_price=today_open,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
        )
