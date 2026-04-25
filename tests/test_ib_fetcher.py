"""Tests for IBFetcher (CPClient-backed)."""
import pytest
import respx
import httpx
from decimal import Decimal

from polara.broker.cp_client import CPClient
from polara.market_data.fetcher import IBFetcher, _cp_period

BASE = "https://cp-gateway:5000/v1/api"


@pytest.fixture
async def fetcher():
    async with respx.mock(base_url=BASE):
        respx.get("/portfolio/accounts").mock(
            return_value=httpx.Response(200, json=[{"accountId": "DU999"}])
        )
        cp = CPClient(base_url=BASE)
        await cp.start()
        yield IBFetcher(cp_client=cp)
        await cp.stop()


# ── _cp_period ─────────────────────────────────────────────────────────────────

def test_cp_period_intraday_small():
    assert _cp_period(10, "5 mins") == "2d"


def test_cp_period_intraday_large():
    # 200 bars × 15 min × 2 = 6000 min = 100h → 5 days
    result = _cp_period(200, "15 mins")
    assert result.endswith("d")


def test_cp_period_daily():
    # 300 bars × 1440 min × 2 = big → should give months or years
    result = _cp_period(300, "1 day")
    assert "m" in result or "y" in result


# ── fetch_bars ─────────────────────────────────────────────────────────────────

@respx.mock
@pytest.mark.asyncio
async def test_fetch_bars_returns_bars():
    respx.get(f"{BASE}/portfolio/accounts").mock(
        return_value=httpx.Response(200, json=[{"accountId": "DU999"}])
    )
    respx.post(f"{BASE}/iserver/secdef/search").mock(
        return_value=httpx.Response(200, json=[{"conid": "265598"}])
    )
    respx.get(f"{BASE}/iserver/marketdata/history").mock(
        return_value=httpx.Response(
            200,
            json={
                "symbol": "AAPL",
                "data": [
                    {"t": 1700000000000, "o": 150.0, "h": 155.0, "l": 149.0, "c": 153.0, "v": 1000},
                    {"t": 1700003600000, "o": 153.0, "h": 158.0, "l": 152.0, "c": 157.0, "v": 1200},
                ],
            },
        )
    )

    cp = CPClient(base_url=BASE)
    await cp.start()
    f = IBFetcher(cp_client=cp)
    bars = await f.fetch_bars("AAPL", 2)
    await cp.stop()

    assert len(bars) == 2
    assert bars[0].symbol == "AAPL"
    assert bars[0].open == Decimal("150.0")
    assert bars[1].close == Decimal("157.0")
    assert isinstance(bars[0].volume, int)


@respx.mock
@pytest.mark.asyncio
async def test_fetch_bars_trims_to_n():
    respx.get(f"{BASE}/portfolio/accounts").mock(
        return_value=httpx.Response(200, json=[{"accountId": "DU999"}])
    )
    respx.post(f"{BASE}/iserver/secdef/search").mock(
        return_value=httpx.Response(200, json=[{"conid": "265598"}])
    )
    # Returns 3 bars but we ask for 2
    respx.get(f"{BASE}/iserver/marketdata/history").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"t": 1700000000000, "o": 100.0, "h": 105.0, "l": 99.0, "c": 103.0, "v": 500},
                    {"t": 1700003600000, "o": 103.0, "h": 108.0, "l": 102.0, "c": 106.0, "v": 600},
                    {"t": 1700007200000, "o": 106.0, "h": 111.0, "l": 105.0, "c": 110.0, "v": 700},
                ]
            },
        )
    )

    cp = CPClient(base_url=BASE)
    await cp.start()
    bars = await IBFetcher(cp_client=cp).fetch_bars("AAPL", 2)
    await cp.stop()

    assert len(bars) == 2
    assert bars[0].close == Decimal("106.0")
    assert bars[1].close == Decimal("110.0")


# ── fetch_quote ────────────────────────────────────────────────────────────────

@respx.mock
@pytest.mark.asyncio
async def test_fetch_quote_returns_quote():
    respx.get(f"{BASE}/portfolio/accounts").mock(
        return_value=httpx.Response(200, json=[{"accountId": "DU999"}])
    )
    respx.post(f"{BASE}/iserver/secdef/search").mock(
        return_value=httpx.Response(200, json=[{"conid": "265598"}])
    )
    respx.get(f"{BASE}/iserver/marketdata/snapshot").mock(
        return_value=httpx.Response(
            200,
            json=[{"conid": 265598, "84": "149.50", "86": "149.75"}],
        )
    )

    cp = CPClient(base_url=BASE)
    await cp.start()
    quote = await IBFetcher(cp_client=cp).fetch_quote("AAPL")
    await cp.stop()

    assert quote.symbol == "AAPL"
    assert quote.bid == Decimal("149.50")
    assert quote.ask == Decimal("149.75")
    assert quote.bid_size >= 0
    assert quote.ask_size >= 0


@respx.mock
@pytest.mark.asyncio
async def test_fetch_quote_raises_if_no_snapshot():
    respx.get(f"{BASE}/portfolio/accounts").mock(
        return_value=httpx.Response(200, json=[{"accountId": "DU999"}])
    )
    respx.post(f"{BASE}/iserver/secdef/search").mock(
        return_value=httpx.Response(200, json=[{"conid": "265598"}])
    )
    respx.get(f"{BASE}/iserver/marketdata/snapshot").mock(
        return_value=httpx.Response(200, json=[])
    )

    cp = CPClient(base_url=BASE)
    await cp.start()
    with pytest.raises(ValueError, match="No snapshot"):
        await IBFetcher(cp_client=cp).fetch_quote("AAPL")
    await cp.stop()


@respx.mock
@pytest.mark.asyncio
async def test_fetch_quote_raises_if_bid_ask_missing():
    respx.get(f"{BASE}/portfolio/accounts").mock(
        return_value=httpx.Response(200, json=[{"accountId": "DU999"}])
    )
    respx.post(f"{BASE}/iserver/secdef/search").mock(
        return_value=httpx.Response(200, json=[{"conid": "265598"}])
    )
    respx.get(f"{BASE}/iserver/marketdata/snapshot").mock(
        return_value=httpx.Response(200, json=[{"conid": 265598}])
    )

    cp = CPClient(base_url=BASE)
    await cp.start()
    with pytest.raises(ValueError, match="not available"):
        await IBFetcher(cp_client=cp).fetch_quote("AAPL")
    await cp.stop()
