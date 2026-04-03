"""MarketDataService — orchestrates IBFetcher + BarStore."""
import logging

from polara.market_data.fetcher import IBFetcher
from polara.market_data.store import BarStore
from polara.schemas.market import Bar, Quote

logger = logging.getLogger(__name__)


class MarketDataService:
    """Fetches bars from IB, persists to DuckDB, returns latest n bars."""

    def __init__(self, fetcher: IBFetcher, store: BarStore) -> None:
        self._fetcher = fetcher
        self._store = store

    async def get_bars(self, symbol: str, n: int, bar_size: str = "5 mins") -> list[Bar]:
        """Fetch and store latest bars; return n most recent (oldest-first).

        Falls back to cached DuckDB data if IB is unavailable.
        """
        try:
            bars = await self._fetcher.fetch_bars(symbol, n=n, bar_size=bar_size)
            self._store.upsert(bars, bar_size=bar_size)
        except Exception:
            logger.error(
                "Failed to fetch bars for %s from IB; using cached data", symbol, exc_info=True
            )
        return self._store.query(symbol, n=n, bar_size=bar_size)

    async def get_latest_quote(self, symbol: str) -> Quote:
        """Return live bid/ask for symbol."""
        return await self._fetcher.fetch_quote(symbol)
