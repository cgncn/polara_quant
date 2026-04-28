"""ConfluentScheduler — multi-timeframe confluence: long-term bias gates intraday signals."""
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from polara.market_data.service import MarketDataService
from polara.order_manager.manager import OrderManager
from polara.research_engine.constants import MAX_BAR_AGE
from polara.research_engine.registry import StrategyRegistry
from polara.risk_guard.exceptions import RiskViolationError
from polara.schemas.signals import Signal

logger = logging.getLogger(__name__)

Bias = Literal["bullish", "bearish", "neutral"]


@dataclass
class ConfluentScheduler:
    """Evaluates long-term strategies to compute a directional bias, then only
    submits intraday signals that agree with that bias."""

    market_data_svc: MarketDataService
    registry: StrategyRegistry
    order_manager: OrderManager
    long_term_ids: list[str]
    intraday_ids: list[str]
    min_bias_strength: Decimal = field(default_factory=lambda: Decimal("0"))
    interval_seconds: int = 900

    async def run(self) -> None:
        while True:
            await self._run_once()
            await asyncio.sleep(self.interval_seconds)

    async def _run_once(self) -> None:
        bias = await self._compute_bias()
        now = datetime.now(UTC)
        for strategy_id in self.intraday_ids:
            try:
                strategy = self.registry.get(strategy_id)
                bars = await self.market_data_svc.get_bars(
                    strategy.symbol,
                    n=strategy.bars_needed,
                    bar_size=strategy.bar_size,
                )
                if not bars:
                    logger.debug(
                        "No bars available for %s — skipping", strategy_id
                    )
                    continue
                bar_age = now - bars[-1].timestamp
                if bar_age > MAX_BAR_AGE:
                    logger.debug(
                        "Most recent bar for %s is %s old (> %s) — market closed, skipping",
                        strategy.symbol,
                        bar_age,
                        MAX_BAR_AGE,
                    )
                    continue
                signal = strategy.on_bars(bars)
                if signal is None:
                    continue
                filtered = self._apply_bias_filter(signal, bias)
                if filtered is None:
                    continue
                await self.order_manager.process_signal(filtered)
            except RiskViolationError as e:
                logger.warning(
                    "Risk violation skipping strategy %s: %s", strategy_id, e
                )
            except Exception:
                logger.error(
                    "Unexpected error in confluent scheduler for strategy %s",
                    strategy_id,
                    exc_info=True,
                )

    async def _compute_bias(self) -> Bias:
        now = datetime.now(UTC)
        signals: list[Signal] = []
        for strategy_id in self.long_term_ids:
            try:
                strategy = self.registry.get(strategy_id)
                bars = await self.market_data_svc.get_bars(
                    strategy.symbol,
                    n=strategy.bars_needed,
                    bar_size=strategy.bar_size,
                )
                if not bars:
                    continue
                bar_age = now - bars[-1].timestamp
                if bar_age > MAX_BAR_AGE:
                    continue
                signal = strategy.on_bars(bars)
                if signal is None:
                    continue
                signals.append(signal)
            except Exception:
                logger.error(
                    "Error computing bias for long-term strategy %s",
                    strategy_id,
                    exc_info=True,
                )

        if not signals:
            return "neutral"

        net_strength = sum((s.strength for s in signals), Decimal("0"))
        avg_strength = net_strength / Decimal(len(signals))

        if avg_strength > self.min_bias_strength:
            return "bullish"
        if avg_strength < -self.min_bias_strength:
            return "bearish"
        return "neutral"

    def _apply_bias_filter(self, signal: Signal, bias: Bias) -> Signal | None:
        if bias == "bullish" and signal.strength <= Decimal("0"):
            return None
        if bias == "bearish" and signal.strength >= Decimal("0"):
            return None
        return signal
