from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from polara.market_data.session import get_session_bars
from polara.research_engine.base import Strategy
from polara.schemas.market import Bar
from polara.schemas.signals import Signal

_ET = ZoneInfo("America/New_York")


def _session_vwap(session_bars: list[Bar]) -> Decimal:
    total_volume = sum(Decimal(b.volume) for b in session_bars)
    if total_volume == 0:
        return Decimal("0")
    return sum(b.close * Decimal(b.volume) for b in session_bars) / total_volume


@dataclass
class VWAPMeanReversionStrategy(Strategy):
    strategy_id: str
    symbol: str
    bar_size: str
    deviation_pct: Decimal = Decimal("0.015")
    stop_loss_pct: Decimal = Decimal("0.01")

    @property
    def bars_needed(self) -> int:
        return 4

    def on_bars(self, bars: list[Bar]) -> Signal | None:
        today = bars[-1].timestamp.astimezone(_ET).date()
        session_bars = get_session_bars(bars, today)

        if len(session_bars) < self.bars_needed:
            return None

        vwap = _session_vwap(session_bars)
        if vwap == 0:
            return None

        current_close = bars[-1].close
        deviation = (current_close - vwap) / vwap

        if deviation < -self.deviation_pct:
            strength = Decimal("1")
        elif deviation > self.deviation_pct:
            strength = Decimal("-1")
        else:
            return None

        take_profit_pct = abs(deviation) - self.deviation_pct

        return Signal(
            signal_id=uuid4(),
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            strength=strength,
            generated_at=datetime.now(UTC),
            reference_price=current_close,
            stop_loss_pct=self.stop_loss_pct,
            take_profit_pct=take_profit_pct,
        )
