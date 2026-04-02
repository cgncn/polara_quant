"""Route-level tests for /broker/* endpoints. Adapter is fully mocked."""
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from polara.api.main import create_app
from polara.broker.adapter import BrokerAdapter, BrokerDisconnectedError
from polara.broker.schemas import (
    AccountInfo,
    BrokerStatus,
    OrderStatus,
    PnLSnapshot,
    Position,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def make_mock_adapter(connected: bool = True) -> MagicMock:
    adapter = MagicMock(spec=BrokerAdapter)
    adapter.get_broker_status = AsyncMock(
        return_value=BrokerStatus(
            connected=connected,
            ib_server_time=utcnow() if connected else None,
            account_id=None,
        )
    )
    adapter.get_account = AsyncMock(
        return_value=AccountInfo(
            net_liquidation=Decimal("100000"),
            cash=Decimal("50000"),
            unrealised_pnl=Decimal("500"),
            realised_pnl=Decimal("200"),
            currency="USD",
            timestamp=utcnow(),
        )
    )
    adapter.get_positions = AsyncMock(
        return_value=[
            Position(
                symbol="AAPL",
                quantity=Decimal("10"),
                avg_cost=Decimal("150"),
                unrealised_pnl=Decimal("50"),
                updated_at=utcnow(),
            )
        ]
    )
    adapter.get_pnl_snapshot = AsyncMock(
        return_value=PnLSnapshot(
            net_liquidation=Decimal("100000"),
            cash=Decimal("50000"),
            unrealised_pnl=Decimal("500"),
            realised_pnl=Decimal("200"),
            snapshot_at=utcnow(),
        )
    )
    adapter.place_order = AsyncMock(return_value=str(uuid4()))
    adapter.cancel_order = AsyncMock(
        return_value=OrderStatus(
            order_id=uuid4(),
            ib_order_id=42,
            status="cancelled",
            submitted_at=utcnow(),
            filled_at=None,
        )
    )
    adapter.list_orders = AsyncMock(return_value=[])
    adapter.get_order_with_fills = AsyncMock(return_value=None)
    adapter.list_pnl_history = AsyncMock(return_value=[])
    return adapter


@pytest.fixture
def app_with_mock_adapter():
    mock_adapter = make_mock_adapter()
    app = create_app()
    app.state.broker_adapter = mock_adapter
    return app, mock_adapter


@pytest.fixture
def app_disconnected():
    mock_adapter = make_mock_adapter(connected=False)
    mock_adapter.get_account = AsyncMock(side_effect=BrokerDisconnectedError("not connected"))
    mock_adapter.get_positions = AsyncMock(side_effect=BrokerDisconnectedError("not connected"))
    app = create_app()
    app.state.broker_adapter = mock_adapter
    return app


# ── GET /broker/status ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_broker_status_200(app_with_mock_adapter):
    app, _ = app_with_mock_adapter
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/broker/status")
    assert resp.status_code == 200
    assert resp.json()["connected"] is True


# ── GET /broker/account ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_broker_account_200(app_with_mock_adapter):
    app, _ = app_with_mock_adapter
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/broker/account")
    assert resp.status_code == 200
    data = resp.json()
    assert data["net_liquidation"] == "100000"
    assert data["currency"] == "USD"


@pytest.mark.asyncio
async def test_broker_account_503_when_disconnected(app_disconnected):
    async with AsyncClient(transport=ASGITransport(app=app_disconnected), base_url="http://test") as client:
        resp = await client.get("/broker/account")
    assert resp.status_code == 503


# ── GET /broker/positions ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_broker_positions_200(app_with_mock_adapter):
    app, _ = app_with_mock_adapter
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/broker/positions")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_broker_positions_503_when_disconnected(app_disconnected):
    async with AsyncClient(transport=ASGITransport(app=app_disconnected), base_url="http://test") as client:
        resp = await client.get("/broker/positions")
    assert resp.status_code == 503


# ── POST /broker/orders ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_order_201(app_with_mock_adapter):
    app, _ = app_with_mock_adapter
    payload = {
        "order_id": str(uuid4()),
        "symbol": "AAPL",
        "side": "buy",
        "quantity": "10",
        "limit_price": "150.00",
        "requested_at": utcnow().isoformat(),
        "strategy_id": "test",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/broker/orders", json=payload)
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_post_order_422_bad_payload(app_with_mock_adapter):
    app, _ = app_with_mock_adapter
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/broker/orders", json={"bad": "data"})
    assert resp.status_code == 422


# ── GET /broker/orders ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_orders_200(app_with_mock_adapter):
    app, _ = app_with_mock_adapter
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/broker/orders")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── GET /broker/orders/{order_id} ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_order_404(app_with_mock_adapter):
    app, _ = app_with_mock_adapter
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/broker/orders/{uuid4()}")
    assert resp.status_code == 404


# ── DELETE /broker/orders/{order_id} ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_order_200(app_with_mock_adapter):
    app, _ = app_with_mock_adapter
    order_id = str(uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(f"/broker/orders/{order_id}")
    assert resp.status_code == 200


# ── GET /broker/pnl/history ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pnl_history_200(app_with_mock_adapter):
    app, _ = app_with_mock_adapter
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/broker/pnl/history")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
