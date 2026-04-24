"""StrategyScheduler — runs registered strategies on a fixed interval."""
import asyncio
import logging
from datetime import UTC, datetime, timedelta

from polara.market_data.service import MarketDataService
from polara.order_manager.manager import OrderManager
from polara.research_engine.registry import StrategyRegistry
from polara.risk_guard.exceptions import RiskViolationError

logger = logging.getLogger(__name__)

# Skip strategy evaluation when the most recent bar is older than this.
# Prevents firing signals on yesterday's stale cache during market close / weekends.
_MAX_BAR_AGE: timedelta = timedelta(hours=2)


class StrategyScheduler:
    """Asyncio background task: poll IB → evaluate strategies → submit signals."""

    def __init__(
        self,
        market_data_svc: MarketDataService,
        registry: StrategyRegistry,
        order_manager: OrderManager,
        interval_seconds: int = 60,
    ) -> None:
        self._market_data = market_data_svc
        self._registry = registry
        self._order_manager = order_manager
        self._interval = interval_seconds

    async def run(self) -> None:
        """Run forever. Call as asyncio.create_task(scheduler.run())."""
        while True:
            await self._run_once()
            await asyncio.sleep(self._interval)

    async def _run_once(self) -> None:
        """One evaluation cycle across all registered strategies."""
        now = datetime.now(UTC)
        for strategy in self._registry.get_all():
            try:
                bars = await self._market_data.get_bars(
                    strategy.symbol,
                    n=strategy.bars_needed,
                    bar_size=strategy.bar_size,
                )
                if not bars:
                    logger.debug(
                        "No bars available for %s — skipping", strategy.strategy_id
                    )
                    continue
                bar_age = now - bars[-1].timestamp
                if bar_age > _MAX_BAR_AGE:
                    logger.debug(
                        "Most recent bar for %s is %s old (> %s) — market closed, skipping",
                        strategy.symbol,
                        bar_age,
                        _MAX_BAR_AGE,
                    )
                    continue
                signal = strategy.on_bars(bars)
                if signal is None:
                    continue
                await self._order_manager.process_signal(signal)
            except RiskViolationError as e:
                logger.warning(
                    "Risk violation skipping strategy %s: %s", strategy.strategy_id, e
                )
            except Exception:
                logger.error(
                    "Unexpected error in scheduler for strategy %s",
                    strategy.strategy_id,
                    exc_info=True,
                )
