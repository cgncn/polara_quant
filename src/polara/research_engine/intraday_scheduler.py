"""IntradayScheduler — StrategyScheduler filtered to intraday bar sizes."""
import logging
from datetime import UTC, datetime

from polara.research_engine.constants import MAX_BAR_AGE
from polara.research_engine.scheduler import StrategyScheduler
from polara.risk_guard.exceptions import RiskViolationError

logger = logging.getLogger(__name__)

INTRADAY_SIZES: frozenset[str] = frozenset({"15 mins", "30 mins"})


class IntradayScheduler(StrategyScheduler):
    """Evaluates only strategies with bar_size in INTRADAY_SIZES."""

    async def _run_once(self) -> None:
        now = datetime.now(UTC)
        for strategy in self._registry.get_all():
            if strategy.bar_size not in INTRADAY_SIZES:
                continue
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
