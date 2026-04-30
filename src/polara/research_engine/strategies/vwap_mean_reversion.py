"""VWAPMeanReversionStrategy — intraday VWAP mean reversion.

VWAP uses typical price (H+L+C)/3 × volume for each bar, accumulated over the session.

Two entry modes (controlled by std_mult):
  std_mult set  → entry when price crosses VWAP ± std_mult × σ (adaptive bands)
  std_mult None → entry when price deviates > deviation_pct from VWAP (fixed %)

Stop: the opposite VWAP band (or deviation_pct when no std bands).
Take-profit: excess deviation beyond the trigger threshold.
All arithmetic in Decimal.
"""
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from polara.research_engine.base import Strategy
from polara.schemas.market import Bar
from polara.schemas.signals import Signal

_ET = ZoneInfo("America/New_York")


def _session_vwap(session_bars: list[Bar]) -> Decimal:
    """VWAP using typical price (H+L+C)/3 × volume. Returns 0 if total volume is 0."""
    total_volume = sum(Decimal(b.volume) for b in session_bars)
    if total_volume == Decimal("0"):
        return Decimal("0")
    return (
        sum(
            (b.high + b.low + b.close) / Decimal("3") * Decimal(b.volume)
            for b in session_bars
        )
        / total_volume
    )


def _session_vwap_std(session_bars: list[Bar], vwap: Decimal) -> Decimal:
    """Volume-weighted standard deviation of typical price around VWAP.

    Returns Decimal("0") when total volume is 0 or variance is non-positive.
    """
    total_volume = sum(Decimal(b.volume) for b in session_bars)
    if total_volume == Decimal("0"):
        return Decimal("0")
    variance = (
        sum(
            Decimal(b.volume) * ((b.high + b.low + b.close) / Decimal("3") - vwap) ** 2
            for b in session_bars
        )
        / total_volume
    )
    if variance <= Decimal("0"):
        return Decimal("0")
    return Decimal(str(math.sqrt(float(variance))))


@dataclass
class VWAPMeanReversionStrategy(Strategy):
    """VWAP mean reversion: buy below lower band, sell above upper band."""

    strategy_id: str
    symbol: str
    bar_size: str
    deviation_pct: Decimal = Decimal("0.010")
    stop_loss_pct: Decimal = Decimal("0.01")
    std_mult: Decimal | None = None

    def __post_init__(self) -> None:
        self.PARAM_GRID = {
            "deviation_pct": ["0.005", "0.010", "0.015", "0.020"],
            "stop_loss_pct": ["0.005", "0.010", "0.015"],
            "std_mult": ["1.0", "1.5", "2.0"],
        }

    @property
    def bars_needed(self) -> int:
        return 3

    def on_bars(self, bars: list[Bar]) -> Signal | None:
        from polara.market_data.session import get_session_bars

        today = bars[-1].timestamp.astimezone(_ET).date()
        session_bars = get_session_bars(bars, today)

        if len(session_bars) < self.bars_needed:
            return None

        vwap = _session_vwap(session_bars)
        if vwap == Decimal("0"):
            return None

        current_close = bars[-1].close

        if self.std_mult is not None:
            std = _session_vwap_std(session_bars, vwap)
            if std == Decimal("0"):
                return None
            band = self.std_mult * std
            upper_band = vwap + band
            lower_band = vwap - band
            if current_close < lower_band:
                strength = Decimal("1")
                deviation = (current_close - vwap) / vwap
                take_profit_pct = abs(deviation) - (band / vwap)
                stop_pct = (upper_band - current_close) / current_close
            elif current_close > upper_band:
                strength = Decimal("-1")
                deviation = (current_close - vwap) / vwap
                take_profit_pct = abs(deviation) - (band / vwap)
                stop_pct = (current_close - lower_band) / current_close
            else:
                return None
            stop_loss_pct = stop_pct if stop_pct > Decimal("0") else self.stop_loss_pct
        else:
            deviation = (current_close - vwap) / vwap
            if deviation < -self.deviation_pct:
                strength = Decimal("1")
            elif deviation > self.deviation_pct:
                strength = Decimal("-1")
            else:
                return None
            take_profit_pct = abs(deviation) - self.deviation_pct
            stop_loss_pct = self.stop_loss_pct

        if take_profit_pct <= Decimal("0"):
            take_profit_pct = None  # type: ignore[assignment]

        return Signal(
            signal_id=uuid4(),
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            strength=strength,
            generated_at=datetime.now(UTC),
            reference_price=current_close,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
        )
