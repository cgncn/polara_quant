"""Tests for GET /strategy/list and POST /strategy/run/{strategy_id}."""
from datetime import datetime, UTC
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
import pytest
from httpx import AsyncClient, ASGITransport

from polara.api.main import create_app
from polara.broker.schemas import OrderStatus
from polara.order_manager.manager import OrderManager
from polara.research_engine.registry import StrategyRegistry
from polara.schemas.signals import Signal


def make_signal() -> Signal:
    return Signal(
        signal_id=uuid4(),
        strategy_id="ma-crossover-aapl",
        symbol="AAPL",
        strength=Decimal("1"),
        generated_at=datetime.now(UTC),
    )


def make_order_status() -> OrderStatus:
    return OrderStatus(
        order_id=uuid4(),
        ib_order_id=None,
        status="submitted",
        submitted_at=datetime.now(UTC),
        filled_at=None,
    )


@pytest.fixture
def app():
    application = create_app()

    mock_registry = MagicMock(spec=StrategyRegistry)
    mock_strategy = MagicMock()
    mock_strategy.strategy_id = "ma-crossover-aapl"
    mock_strategy.symbol = "AAPL"
    mock_strategy.bars_needed = 51
    mock_strategy.bar_size = "5 mins"
    mock_strategy.on_bars = MagicMock(return_value=make_signal())
    mock_registry.get_all = MagicMock(return_value=[mock_strategy])
    mock_registry.get = MagicMock(return_value=mock_strategy)

    mock_manager = AsyncMock(spec=OrderManager)
    mock_manager.process_signal = AsyncMock(return_value=make_order_status())

    mock_market_data = AsyncMock()
    mock_market_data.get_bars = AsyncMock(return_value=[])

    application.state.strategy_registry = mock_registry
    application.state.order_manager = mock_manager
    application.state.market_data_svc = mock_market_data
    return application


@pytest.mark.asyncio
async def test_post_strategy_run_returns_200(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/strategy/run/ma-crossover-aapl")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_post_strategy_run_unknown_returns_404(app):
    app.state.strategy_registry.get = MagicMock(side_effect=KeyError("unknown"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/strategy/run/unknown-strategy")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_post_strategy_run_no_signal_returns_204(app):
    app.state.strategy_registry.get = MagicMock(
        return_value=MagicMock(
            strategy_id="ma-crossover-aapl",
            symbol="AAPL",
            bars_needed=51,
            bar_size="5 mins",
            on_bars=MagicMock(return_value=None),
        )
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/strategy/run/ma-crossover-aapl")
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_get_strategy_list_returns_registered_strategies(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/strategy/list")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["strategy_id"] == "ma-crossover-aapl"
