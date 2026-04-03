"""Tests for GET /market-data/bars/{symbol} and GET /market-data/quote/{symbol}."""
from datetime import datetime, UTC
from decimal import Decimal
from unittest.mock import AsyncMock
import pytest
from httpx import AsyncClient, ASGITransport

from polara.api.main import create_app
from polara.market_data.service import MarketDataService
from polara.schemas.market import Bar, Quote


def make_bar(symbol: str = "AAPL") -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=datetime(2026, 4, 3, 10, 0, tzinfo=UTC),
        open=Decimal("170.00"),
        high=Decimal("171.00"),
        low=Decimal("169.50"),
        close=Decimal("170.50"),
        volume=1000,
    )


def make_quote(symbol: str = "AAPL") -> Quote:
    return Quote(
        symbol=symbol,
        timestamp=datetime(2026, 4, 3, 10, 0, tzinfo=UTC),
        bid=Decimal("170.00"),
        ask=Decimal("170.10"),
        bid_size=100,
        ask_size=200,
    )


@pytest.fixture
def mock_market_data_svc():
    svc = AsyncMock(spec=MarketDataService)
    svc.get_bars = AsyncMock(return_value=[make_bar()])
    svc.get_latest_quote = AsyncMock(return_value=make_quote())
    return svc


@pytest.fixture
def app(mock_market_data_svc):
    application = create_app()
    application.state.market_data_svc = mock_market_data_svc
    return application


@pytest.mark.asyncio
async def test_get_bars_returns_200(app, mock_market_data_svc):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/market-data/bars/AAPL")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["symbol"] == "AAPL"
    assert data[0]["close"] == "170.50"


@pytest.mark.asyncio
async def test_get_bars_passes_n_parameter(app, mock_market_data_svc):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/market-data/bars/AAPL?n=50")
    mock_market_data_svc.get_bars.assert_called_once_with("AAPL", n=50, bar_size="5 mins")


@pytest.mark.asyncio
async def test_get_quote_returns_200(app, mock_market_data_svc):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/market-data/quote/AAPL")
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "AAPL"
    assert data["bid"] == "170.00"


@pytest.mark.asyncio
async def test_get_bars_503_when_service_unavailable(app, mock_market_data_svc):
    mock_market_data_svc.get_bars = AsyncMock(side_effect=Exception("IB unavailable"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/market-data/bars/AAPL")
    assert response.status_code == 503
