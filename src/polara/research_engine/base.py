"""Strategy — abstract base class for all strategy sleeves."""
from abc import ABC, abstractmethod

from polara.schemas.market import Bar
from polara.schemas.signals import Signal


class Strategy(ABC):
    """Base class for strategy sleeves.

    Subclasses must define class attributes strategy_id, symbol,
    bars_needed, and bar_size, and implement on_bars().
    """

    strategy_id: str
    symbol: str
    bars_needed: int  # Number of bars the strategy needs for a valid signal
    bar_size: str     # IB bar size string, e.g. "5 mins"

    @abstractmethod
    def on_bars(self, bars: list[Bar]) -> Signal | None:
        """Evaluate bars and return a Signal, or None if no signal."""
        ...
