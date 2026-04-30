"""EMABounceStrategy — price pulls back to slow EMA then resumes in trend direction.

Trend definition:
  fast_ema > slow_ema → bullish
  fast_ema < slow_ema → bearish

Entry conditions (bullish):
  1. fast_ema[-1] > slow_ema[-1]
  2. |close[-1] - slow_ema[-1]| / slow_ema[-1] <= touch_pct (price near slow EMA)
  3. volume[-1] > avg_volume * volume_factor (elevated volume)
  4. close[-1] > close[-2] (last bar resumed upward)

Bearish: symmetric.
All arithmetic in Decimal. Bar.volume is int — wrapped in Decimal() before arithmetic.
"""
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from polara.research_engine.base import Strategy
from polara.research_engine.strategies.indicators import _compute_ema
from polara.schemas.market import Bar
from polara.schemas.signals import Signal


@dataclass
class EMABounceStrategy(Strategy):
    """EMA bounce: buy when price pulls back to slow EMA in an uptrend (and reverse)."""

    strategy_id: str
    symbol: str
    bar_size: str
    ema_fast: int = 9
    ema_slow: int = 21
    touch_pct: Decimal = Decimal("0.005")
    volume_factor: Decimal = Decimal("1.2")
    stop_loss_pct: Decimal | None = None
    take_profit_pct: Decimal | None = None

    def __post_init__(self) -> None:
        self.PARAM_GRID = {
            "ema_fast": [5, 9, 13],
            "ema_slow": [21, 34, 55],
            "touch_pct": ["0.003", "0.005", "0.008"],
            "volume_factor": ["1.0", "1.2", "1.5"],
        }

    @property
    def bars_needed(self) -> int:  # type: ignore[override]
        # Need ema_slow bars to seed the EMA, plus 1 prior bar for close direction
        return self.ema_slow + 1

    def on_bars(self, bars: list[Bar]) -> Signal | None:
        """Return Signal if price bounces off slow EMA in the trend direction."""
        if len(bars) < self.bars_needed:
            return None

        closes = [b.close for b in bars]
        volumes = [Decimal(b.volume) for b in bars]

        fast_ema_series = _compute_ema(closes, self.ema_fast)
        slow_ema_series = _compute_ema(closes, self.ema_slow)

        if not fast_ema_series or not slow_ema_series:
            return None

        fast_now = fast_ema_series[-1]
        slow_now = slow_ema_series[-1]
        close_now = closes[-1]
        close_prev = closes[-2]

        if slow_now == Decimal("0"):
            return None

        distance_pct = abs(close_now - slow_now) / slow_now
        in_touch_zone = distance_pct <= self.touch_pct

        avg_volume = sum(volumes) / Decimal(len(volumes))
        volume_ok = avg_volume > Decimal("0") and volumes[-1] > avg_volume * self.volume_factor

        bullish_trend = fast_now > slow_now
        bearish_trend = fast_now < slow_now

        if bullish_trend and in_touch_zone and volume_ok and close_now > close_prev:
            strength = Decimal("1")
        elif bearish_trend and in_touch_zone and volume_ok and close_now < close_prev:
            strength = Decimal("-1")
        else:
            return None

        return Signal(
            signal_id=uuid4(),
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            strength=strength,
            generated_at=datetime.now(UTC),
            reference_price=close_now,
            stop_loss_pct=self.stop_loss_pct,
            take_profit_pct=self.take_profit_pct,
        )
