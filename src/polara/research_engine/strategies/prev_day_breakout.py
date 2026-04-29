from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from polara.market_data.session import get_prev_session_bars, get_session_bars
from polara.research_engine.base import Strategy
from polara.schemas.market import Bar
from polara.schemas.signals import Signal

_ET = ZoneInfo("America/New_York")


@dataclass
class PrevDayBreakoutStrategy(Strategy):
    """Previous Day Breakout: signal when price exits the prior session range on elevated volume."""

    strategy_id: str
    symbol: str
    bar_size: str
    volume_factor: Decimal = Decimal("1.5")

    def __post_init__(self) -> None:
        self.PARAM_GRID = {
            "volume_factor": ["1.2", "1.5", "2.0", "2.5"],
        }

    @property
    def bars_needed(self) -> int:  # type: ignore[override]
        return 40

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

        # Zero-volume guard: treat as no volume confirmation
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

        stop_loss_pct = Decimal("0.01")

        return Signal(
            signal_id=uuid4(),
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            strength=strength,
            generated_at=datetime.now(UTC),
            reference_price=last_bar.close,
            stop_loss_pct=stop_loss_pct,
        )
