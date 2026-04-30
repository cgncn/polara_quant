"""BollingerBandStrategy — volatility-adaptive mean reversion.

Middle band = SMA(period)
Upper band  = middle + num_std × σ
Lower band  = middle − num_std × σ

Buy when close crosses below the lower band (oversold relative to volatility).
Sell when close crosses above the upper band (overbought relative to volatility).
All arithmetic in Decimal.
"""
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from polara.research_engine.base import Strategy
from polara.research_engine.strategies.indicators import _compute_atr
from polara.schemas.market import Bar
from polara.schemas.signals import Signal


def _bollinger(
    closes: list[Decimal], period: int, num_std: Decimal
) -> tuple[Decimal, Decimal, Decimal]:
    """Return (middle, upper, lower) Bollinger Bands for the last `period` closes."""
    window = closes[-period:]
    middle = sum(window, Decimal(0)) / Decimal(period)
    variance = sum((c - middle) ** 2 for c in window) / Decimal(period)
    std = Decimal(str(math.sqrt(float(variance))))
    band = num_std * std
    return middle, middle + band, middle - band


@dataclass
class BollingerBandStrategy(Strategy):
    """Bollinger Band mean reversion: buy at lower band, sell at upper band."""

    strategy_id: str
    symbol: str
    period: int
    num_std: Decimal
    quantity: Decimal
    bar_size: str
    stop_loss_pct: Decimal | None = None
    take_profit_pct: Decimal | None = None
    atr_period: int = 14
    atr_stop_multiplier: Decimal | None = None

    def __post_init__(self) -> None:
        self.PARAM_GRID = {
            "period": [10, 20, 30],
            "num_std": ["1.5", "2.0", "2.5"],
            "atr_stop_multiplier": ["1.5", "2.0", "2.5"],
        }

    @property
    def bars_needed(self) -> int:  # type: ignore[override]
        return max(self.period + 1, self.atr_period + 2)

    def on_bars(self, bars: list[Bar]) -> Signal | None:
        """Return Signal if close crossed a Bollinger Band on the last bar, else None."""
        if len(bars) < self.bars_needed:
            return None

        closes = [b.close for b in bars]
        _, upper_now, lower_now = _bollinger(closes, self.period, self.num_std)
        _, upper_prev, lower_prev = _bollinger(closes[:-1], self.period, self.num_std)

        close_now = closes[-1]
        close_prev = closes[-2]

        if close_prev >= lower_prev and close_now < lower_now:
            strength = Decimal("1")
        elif close_prev <= upper_prev and close_now > upper_now:
            strength = Decimal("-1")
        else:
            return None

        if self.atr_stop_multiplier is not None:
            atr = _compute_atr(bars, self.atr_period)
            if atr > Decimal("0") and close_now > Decimal("0"):
                stop_loss_pct = atr * self.atr_stop_multiplier / close_now
            else:
                stop_loss_pct = self.stop_loss_pct
        else:
            stop_loss_pct = self.stop_loss_pct

        return Signal(
            signal_id=uuid4(),
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            strength=strength,
            generated_at=datetime.now(UTC),
            reference_price=bars[-1].close,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=self.take_profit_pct,
        )
