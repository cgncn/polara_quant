"""Tests for market_data.fetcher — IBFetcher."""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from polara.market_data.fetcher import IBFetcher
from polara.schemas.market import Bar, Quote


def make_mock_ib_bar(
    *,
    date: str = "20260403 10:00:00",
    open_: float = 170.0,
    high: float = 171.0,
    low: float = 169.5,
    close: float = 170.5,
    volume: float = 1000.0,
) -> MagicMock:
    bar = MagicMock()
    bar.date = date
    bar.open = open_
    bar.high = high
    bar.low = low
    bar.close = close
    bar.volume = volume
    return bar


def make_mock_ticker(
    bid: float = 170.0,
    ask: float = 170.1,
    bid_size: float = 100.0,
    ask_size: float = 200.0,
) -> MagicMock:
    ticker = MagicMock()
    ticker.bid = bid
    ticker.ask = ask
    ticker.bidSize = bid_size
    ticker.askSize = ask_size
    return ticker


@pytest.mark.asyncio
async def test_fetch_bars_returns_bars():
    mock_ib = AsyncMock()
    mock_ib.reqHistoricalDataAsync = AsyncMock(
        return_value=[make_mock_ib_bar(close=170.5), make_mock_ib_bar(close=171.0)]
    )
    fetcher = IBFetcher(mock_ib)
    bars = await fetcher.fetch_bars("AAPL", n=2, bar_size="5 mins")
    assert len(bars) == 2
    assert all(isinstance(b, Bar) for b in bars)


@pytest.mark.asyncio
async def test_fetch_bars_prices_are_decimal():
    mock_ib = AsyncMock()
    mock_ib.reqHistoricalDataAsync = AsyncMock(
        return_value=[make_mock_ib_bar(close=170.5)]
    )
    fetcher = IBFetcher(mock_ib)
    bars = await fetcher.fetch_bars("AAPL", n=1, bar_size="5 mins")
    assert isinstance(bars[0].close, Decimal)
    assert isinstance(bars[0].open, Decimal)
    assert isinstance(bars[0].volume, int)
    assert bars[0].close == Decimal("170.5")


@pytest.mark.asyncio
async def test_fetch_bars_timestamps_are_utc():
    mock_ib = AsyncMock()
    mock_ib.reqHistoricalDataAsync = AsyncMock(
        return_value=[make_mock_ib_bar(date="20260403 10:00:00")]
    )
    fetcher = IBFetcher(mock_ib)
    bars = await fetcher.fetch_bars("AAPL", n=1, bar_size="5 mins")
    assert bars[0].timestamp.tzinfo is not None
    assert bars[0].timestamp.tzinfo.utcoffset(bars[0].timestamp).total_seconds() == 0


@pytest.mark.asyncio
async def test_fetch_bars_symbol_set_correctly():
    mock_ib = AsyncMock()
    mock_ib.reqHistoricalDataAsync = AsyncMock(
        return_value=[make_mock_ib_bar()]
    )
    fetcher = IBFetcher(mock_ib)
    bars = await fetcher.fetch_bars("MSFT", n=1, bar_size="5 mins")
    assert bars[0].symbol == "MSFT"


@pytest.mark.asyncio
async def test_fetch_bars_daily_bar_date_format():
    """IB uses YYYYMMDD (no time) for daily bars — ensure this parses correctly."""
    mock_ib = AsyncMock()
    mock_ib.reqHistoricalDataAsync = AsyncMock(
        return_value=[make_mock_ib_bar(date="20260403")]
    )
    fetcher = IBFetcher(mock_ib)
    bars = await fetcher.fetch_bars("AAPL", n=1, bar_size="1 day")
    assert len(bars) == 1
    assert bars[0].timestamp.tzinfo is not None
    assert bars[0].timestamp.year == 2026
    assert bars[0].timestamp.month == 4
    assert bars[0].timestamp.day == 3


@pytest.mark.asyncio
async def test_fetch_bars_truncates_to_n():
    """IB may return more bars than requested; only last n should be returned."""
    mock_ib = AsyncMock()
    mock_ib.reqHistoricalDataAsync = AsyncMock(
        return_value=[
            make_mock_ib_bar(close=str(float(100 + i))) for i in range(5)
        ]
    )
    fetcher = IBFetcher(mock_ib)
    bars = await fetcher.fetch_bars("AAPL", n=3, bar_size="5 mins")
    assert len(bars) == 3
    # Should be the last 3 bars (most recent)
    assert bars[-1].close == Decimal("104.0")


@pytest.mark.asyncio
async def test_fetch_quote_returns_quote():
    mock_ib = AsyncMock()
    mock_ib.reqTickersAsync = AsyncMock(return_value=[make_mock_ticker()])
    fetcher = IBFetcher(mock_ib)
    quote = await fetcher.fetch_quote("AAPL")
    assert isinstance(quote, Quote)
    assert quote.symbol == "AAPL"
    assert isinstance(quote.bid, Decimal)
    assert isinstance(quote.ask, Decimal)


@pytest.mark.asyncio
async def test_fetch_quote_prices_are_decimal():
    mock_ib = AsyncMock()
    mock_ib.reqTickersAsync = AsyncMock(return_value=[make_mock_ticker(bid=170.0, ask=170.1)])
    fetcher = IBFetcher(mock_ib)
    quote = await fetcher.fetch_quote("AAPL")
    assert quote.bid == Decimal("170.0")
    assert quote.ask == Decimal("170.1")


@pytest.mark.asyncio
async def test_fetch_quote_raises_on_empty_response():
    mock_ib = AsyncMock()
    mock_ib.reqTickersAsync = AsyncMock(return_value=[])
    fetcher = IBFetcher(mock_ib)
    with pytest.raises(ValueError, match="No ticker data"):
        await fetcher.fetch_quote("AAPL")
