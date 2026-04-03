"""StrategyRegistry — holds registered strategy instances."""
from polara.research_engine.base import Strategy


class StrategyRegistry:
    """Registry of strategy instances, keyed by strategy_id."""

    def __init__(self) -> None:
        self._strategies: dict[str, Strategy] = {}

    def register(self, strategy: Strategy) -> None:
        if strategy.strategy_id in self._strategies:
            raise ValueError(f"Strategy '{strategy.strategy_id}' already registered")
        self._strategies[strategy.strategy_id] = strategy

    def get(self, strategy_id: str) -> Strategy:
        if strategy_id not in self._strategies:
            raise KeyError(f"Strategy '{strategy_id}' not found")
        return self._strategies[strategy_id]

    def get_all(self) -> list[Strategy]:
        return list(self._strategies.values())
