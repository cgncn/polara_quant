"""PromotionGate — manual gate for promoting strategies from paper to live.

No strategy can self-promote. Promotion requires a passing backtest on record.
"""
from polara.backtester.service import BacktestService
from polara.research_engine.status_service import StrategyStatusService


class PromotionError(Exception):
    """Raised when promotion conditions are not met."""


class PromotionGate:
    """Manual promotion gate. Enforces: passing backtest required, correct current status."""

    def __init__(
        self,
        status_service: StrategyStatusService,
        backtest_service: BacktestService,
    ) -> None:
        self._status = status_service
        self._backtest = backtest_service

    async def promote(self, strategy_id: str) -> None:
        """Promote strategy_id from paper/paused to live.

        Raises PromotionError if:
        - No passing backtest result exists
        - Current status is not 'paper' or 'paused'
        """
        if not await self._backtest.has_passing_result(strategy_id):
            raise PromotionError(
                f"Strategy '{strategy_id}' has no passing backtest result. "
                "Run POST /strategy/{id}/validate first."
            )
        current = await self._status.get_status(strategy_id)
        if current not in ("paper", "paused"):
            raise PromotionError(
                f"Strategy '{strategy_id}' must be in paper or paused state to promote. "
                f"Current status: {current!r}"
            )
        await self._status.set_status(strategy_id, "live")

    async def demote(self, strategy_id: str) -> None:
        """Demote strategy_id from live to paper.

        Raises PromotionError if current status is not 'live'.
        """
        current = await self._status.get_status(strategy_id)
        if current != "live":
            raise PromotionError(
                f"Strategy '{strategy_id}' is not live. Current status: {current!r}"
            )
        await self._status.set_status(strategy_id, "paper")
