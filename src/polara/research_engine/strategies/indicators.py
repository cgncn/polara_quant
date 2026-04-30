"""Shared technical indicator utilities.

All arithmetic uses Decimal. math.sqrt results are wrapped via Decimal(str(...)).
Bar.volume is int — wrap in Decimal(b.volume) before arithmetic.
"""
from decimal import Decimal

from polara.schemas.market import Bar


def _compute_atr(bars: list[Bar], period: int) -> Decimal:
    """Compute Average True Range using Wilder's smoothing.

    True Range = max(high - low, |high - prev_close|, |low - prev_close|).
    Requires len(bars) >= period + 1. Returns Decimal("0") if insufficient.
    """
    if len(bars) < period + 1:
        return Decimal("0")

    trs: list[Decimal] = []
    for i in range(1, len(bars)):
        prev_close = bars[i - 1].close
        high = bars[i].high
        low = bars[i].low
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)

    avg = sum(trs[:period], Decimal(0)) / Decimal(period)
    for tr in trs[period:]:
        avg = (avg * Decimal(period - 1) + tr) / Decimal(period)

    return avg


def _compute_ema(values: list[Decimal], period: int) -> list[Decimal]:
    """Compute full EMA series seeded from the initial SMA.

    Returns [] if len(values) < period. Returned list has same length as values.
    """
    if len(values) < period:
        return []

    k = Decimal(2) / Decimal(period + 1)
    seed = sum(values[:period], Decimal(0)) / Decimal(period)
    result: list[Decimal] = [seed] * period
    for v in values[period:]:
        result.append(result[-1] + k * (v - result[-1]))
    return result
