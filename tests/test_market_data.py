"""Tests for market_data.fetcher — IBFetcher (CPClient-backed)."""
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from polara.market_data.fetcher import IBFetcher
from polara.schemas.market import Bar, Quote


def make_mock_cp(bars_data=None, snapshot_data=None) -> MagicMock:
    cp = MagicMock()
    cp.get_conid = AsyncMock(return_value=265598)
    _bars = bars_data if bars_data is not None else [
        {"t": 1743674400000, "o": 170.0, "h": 171.0, "l": 169.5, "c": 170.5, "v": 1000}
    ]
    cp.historical_bars = AsyncMock(return_value={"data": _bars})
    _snap = snapshot_data if snapshot_data is not None else [
        {"conid": 265598, "84": "170.0", "86": "170.1"}
    ]
    cp.market_snapshot = AsyncMock(return_value=_snap)
    return cp


@pytest.mark.asyncio
async def test_fetch_bars_returns_bars():
    cp = make_mock_cp(bars_data=[
        {"t": 1743674400000, "o": 170.0, "h": 171.0, "l": 169.5, "c": 170.5, "v": 1000},
        {"t": 1743678000000, "o": 170.5, "h": 172.0, "l": 170.0, "c": 171.0, "v": 1200},
    ])
    fetcher = IBFetcher(cp_client=cp)
    bars = await fetcher.fetch_bars("AAPL", n=2, bar_size="5 mins")
    assert len(bars) == 2
    assert all(isinstance(b, Bar) for b in bars)


@pytest.mark.asyncio
async def test_fetch_bars_prices_are_decimal():
    cp = make_mock_cp(bars_data=[
        {"t": 1743674400000, "o": 170.0, "h": 171.0, "l": 169.5, "c": 170.5, "v": 1000}
    ])
    fetcher = IBFetcher(cp_client=cp)
    bars = await fetcher.fetch_bars("AAPL", n=1, bar_size="5 mins")
    assert isinstance(bars[0].close, Decimal)
    assert isinstance(bars[0].open, Decimal)
    assert isinstance(bars[0].volume, int)
    assert bars[0].close == Decimal("170.5")


@pytest.mark.asyncio
async def test_fetch_bars_timestamps_are_utc():
    cp = make_mock_cp(bars_data=[
        {"t": 1743674400000, "o": 170.0, "h": 171.0, "l": 169.5, "c": 170.5, "v": 1000}
    ])
    fetcher = IBFetcher(cp_client=cp)
    bars = await fetcher.fetch_bars("AAPL", n=1, bar_size="5 mins")
    assert bars[0].timestamp.tzinfo is not None
    assert bars[0].timestamp.tzinfo.utcoffset(bars[0].timestamp).total_seconds() == 0


@pytest.mark.asyncio
async def test_fetch_bars_symbol_set_correctly():
    cp = make_mock_cp(bars_data=[
        {"t": 1743674400000, "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5, "v": 500}
    ])
    fetcher = IBFetcher(cp_client=cp)
    bars = await fetcher.fetch_bars("MSFT", n=1, bar_size="5 mins")
    assert bars[0].symbol == "MSFT"


@pytest.mark.asyncio
async def test_fetch_bars_timestamp_from_epoch_ms():
    """CP API delivers timestamps as Unix ms — verify conversion."""
    ts_ms = 1743674400000
    expected = datetime.fromtimestamp(ts_ms / 1000, tz=UTC)
    cp = make_mock_cp(bars_data=[
        {"t": ts_ms, "o": 170.0, "h": 171.0, "l": 169.5, "c": 170.5, "v": 1000}
    ])
    fetcher = IBFetcher(cp_client=cp)
    bars = await fetcher.fetch_bars("AAPL", n=1, bar_size="1 day")
    assert bars[0].timestamp == expected


@pytest.mark.asyncio
async def test_fetch_bars_truncates_to_n():
    cp = make_mock_cp(bars_data=[
        {"t": 1743674400000 + i * 300000, "o": 100.0 + i, "h": 105.0 + i, "l": 99.0 + i, "c": 100.0 + i, "v": 500}
        for i in range(5)
    ])
    fetcher = IBFetcher(cp_client=cp)
    bars = await fetcher.fetch_bars("AAPL", n=3, bar_size="5 mins")
    assert len(bars) == 3
    assert bars[-1].close == Decimal("104.0")


@pytest.mark.asyncio
async def test_fetch_quote_returns_quote():
    cp = make_mock_cp(snapshot_data=[{"conid": 265598, "84": "170.0", "86": "170.1"}])
    fetcher = IBFetcher(cp_client=cp)
    quote = await fetcher.fetch_quote("AAPL")
    assert isinstance(quote, Quote)
    assert quote.symbol == "AAPL"
    assert isinstance(quote.bid, Decimal)
    assert isinstance(quote.ask, Decimal)


@pytest.mark.asyncio
async def test_fetch_quote_prices_are_decimal():
    cp = make_mock_cp(snapshot_data=[{"conid": 265598, "84": "170.0", "86": "170.1"}])
    fetcher = IBFetcher(cp_client=cp)
    quote = await fetcher.fetch_quote("AAPL")
    assert quote.bid == Decimal("170.0")
    assert quote.ask == Decimal("170.1")


@pytest.mark.asyncio
async def test_fetch_quote_raises_on_empty_response():
    cp = make_mock_cp(snapshot_data=[])
    fetcher = IBFetcher(cp_client=cp)
    with pytest.raises(ValueError, match="No snapshot"):
        await fetcher.fetch_quote("AAPL")


# ── BarStore tests ──────────────────────────────────────────────────────────

from polara.market_data.store import BarStore


def make_bar(
    symbol: str = "AAPL",
    ts: str = "2026-04-03T10:00:00+00:00",
    close: str = "170.50",
) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=datetime.fromisoformat(ts),
        open=Decimal("170.00"),
        high=Decimal("171.00"),
        low=Decimal("169.50"),
        close=Decimal(close),
        volume=1000,
    )


def test_store_upsert_and_query(tmp_path):
    store = BarStore(str(tmp_path / "test.duckdb"))
    bars = [make_bar(ts="2026-04-03T10:00:00+00:00"), make_bar(ts="2026-04-03T10:05:00+00:00")]
    store.upsert(bars, bar_size="5 mins")
    result = store.query("AAPL", n=10, bar_size="5 mins")
    assert len(result) == 2
    assert all(isinstance(b, Bar) for b in result)
    assert all(isinstance(b.close, Decimal) for b in result)


def test_store_upsert_deduplicates(tmp_path):
    store = BarStore(str(tmp_path / "test.duckdb"))
    bar = make_bar(ts="2026-04-03T10:00:00+00:00", close="170.50")
    store.upsert([bar], bar_size="5 mins")
    updated_bar = make_bar(ts="2026-04-03T10:00:00+00:00", close="171.00")
    store.upsert([updated_bar], bar_size="5 mins")
    result = store.query("AAPL", n=10, bar_size="5 mins")
    assert len(result) == 1
    assert result[0].close == Decimal("171.00")


def test_store_query_returns_n_latest(tmp_path):
    store = BarStore(str(tmp_path / "test.duckdb"))
    bars = [
        make_bar(ts=f"2026-04-03T{10 + i:02d}:00:00+00:00", close=str(170 + i))
        for i in range(5)
    ]
    store.upsert(bars, bar_size="5 mins")
    result = store.query("AAPL", n=3, bar_size="5 mins")
    assert len(result) == 3
    assert result[-1].close == Decimal("174")


def test_store_query_timestamps_are_utc(tmp_path):
    store = BarStore(str(tmp_path / "test.duckdb"))
    store.upsert([make_bar()], bar_size="5 mins")
    result = store.query("AAPL", n=1, bar_size="5 mins")
    assert result[0].timestamp.tzinfo is not None


def test_store_query_empty_returns_empty(tmp_path):
    store = BarStore(str(tmp_path / "test.duckdb"))
    result = store.query("AAPL", n=10, bar_size="5 mins")
    assert result == []


# ── MarketDataService tests ─────────────────────────────────────────────────

from polara.market_data.service import MarketDataService


@pytest.mark.asyncio
async def test_service_get_bars_fetches_and_stores(tmp_path):
    cp = make_mock_cp(bars_data=[
        {"t": 1743674400000, "o": 170.0, "h": 171.0, "l": 169.5, "c": 170.5, "v": 1000}
    ])
    store = BarStore(str(tmp_path / "test.duckdb"))
    fetcher = IBFetcher(cp_client=cp)
    svc = MarketDataService(fetcher=fetcher, store=store)
    bars = await svc.get_bars("AAPL", n=1, bar_size="5 mins")
    assert len(bars) == 1
    assert bars[0].symbol == "AAPL"


@pytest.mark.asyncio
async def test_service_get_bars_returns_from_store_on_fetch_failure(tmp_path):
    """If CP fetch fails, service returns whatever is already in the store."""
    store = BarStore(str(tmp_path / "test.duckdb"))
    store.upsert([make_bar()], bar_size="5 mins")

    cp = MagicMock()
    cp.get_conid = AsyncMock(side_effect=Exception("CP unavailable"))
    fetcher = IBFetcher(cp_client=cp)
    svc = MarketDataService(fetcher=fetcher, store=store)
    bars = await svc.get_bars("AAPL", n=1, bar_size="5 mins")
    assert len(bars) == 1


@pytest.mark.asyncio
async def test_service_get_latest_quote(tmp_path):
    cp = make_mock_cp(snapshot_data=[{"conid": 265598, "84": "169.9", "86": "170.1"}])
    store = BarStore(str(tmp_path / "test.duckdb"))
    fetcher = IBFetcher(cp_client=cp)
    svc = MarketDataService(fetcher=fetcher, store=store)
    quote = await svc.get_latest_quote("AAPL")
    assert quote.symbol == "AAPL"
    assert quote.bid == Decimal("169.9")
