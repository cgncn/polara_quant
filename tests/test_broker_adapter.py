"""Tests for BrokerAdapter — ib_async client is fully mocked."""
import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from polara.broker.adapter import BrokerAdapter, BrokerDisconnectedError
from polara.broker.schemas import AccountInfo, BrokerStatus, PnLSnapshot, Position
from polara.schemas.orders import OrderRequest


def make_mock_ib_client(connected: bool = True) -> MagicMock:
    """Build a minimal mock IBClient."""
    client = MagicMock()
    client.connected = connected
    ib = MagicMock()
    ib.isConnected.return_value = connected
    client.ib = ib
    return client


def utcnow() -> datetime:
    return datetime.now(UTC)


def make_order_request() -> OrderRequest:
    return OrderRequest(
        order_id=uuid4(),
        symbol="AAPL",
        side="buy",
        quantity=Decimal("10"),
        limit_price=Decimal("150.00"),
        requested_at=utcnow(),
        strategy_id="test-strategy",
    )


# ── BrokerStatus ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_broker_status_connected():
    client = make_mock_ib_client(connected=True)
    client.ib.reqCurrentTimeAsync = AsyncMock(return_value=1000000)
    adapter = BrokerAdapter(ib_client=client, db_session_factory=AsyncMock())
    status = await adapter.get_broker_status()
    assert isinstance(status, BrokerStatus)
    assert status.connected is True


@pytest.mark.asyncio
async def test_get_broker_status_disconnected():
    client = make_mock_ib_client(connected=False)
    adapter = BrokerAdapter(ib_client=client, db_session_factory=AsyncMock())
    status = await adapter.get_broker_status()
    assert status.connected is False
    assert status.ib_server_time is None


# ── AccountInfo ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_account_disconnected_raises():
    client = make_mock_ib_client(connected=False)
    adapter = BrokerAdapter(ib_client=client, db_session_factory=AsyncMock())
    with pytest.raises(BrokerDisconnectedError):
        await adapter.get_account()


@pytest.mark.asyncio
async def test_get_account_returns_account_info():
    client = make_mock_ib_client(connected=True)

    def make_av(tag: str, value: str, currency: str = "USD") -> MagicMock:
        av = MagicMock()
        av.tag = tag
        av.value = value
        av.currency = currency
        return av

    client.ib.reqAccountSummaryAsync = AsyncMock(return_value=[
        make_av("NetLiquidation", "100000.00"),
        make_av("TotalCashValue", "50000.00"),
        make_av("UnrealizedPnL", "500.00"),
        make_av("RealizedPnL", "200.00"),
    ])

    adapter = BrokerAdapter(ib_client=client, db_session_factory=AsyncMock())
    info = await adapter.get_account()
    assert isinstance(info, AccountInfo)
    assert info.net_liquidation == Decimal("100000.00")
    assert info.cash == Decimal("50000.00")
    assert info.currency == "USD"


# ── Positions ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_positions_disconnected_raises():
    client = make_mock_ib_client(connected=False)
    adapter = BrokerAdapter(ib_client=client, db_session_factory=AsyncMock())
    with pytest.raises(BrokerDisconnectedError):
        await adapter.get_positions()


@pytest.mark.asyncio
async def test_get_positions_returns_list():
    client = make_mock_ib_client(connected=True)

    mock_pos = MagicMock()
    mock_pos.contract.symbol = "AAPL"
    mock_pos.position = 10.0   # ib_async returns float — adapter must convert
    mock_pos.avgCost = 150.0
    mock_pos.unrealPnl = 50.0
    client.ib.positions.return_value = [mock_pos]

    adapter = BrokerAdapter(ib_client=client, db_session_factory=AsyncMock())
    positions = await adapter.get_positions()
    assert len(positions) == 1
    p = positions[0]
    assert isinstance(p, Position)
    assert p.symbol == "AAPL"
    assert p.quantity == Decimal("10")   # converted from float
    assert p.avg_cost == Decimal("150")  # converted from float
    assert isinstance(p.unrealised_pnl, Decimal)
    assert isinstance(p.unrealised_pnl, Decimal)  # NOT a float


# ── place_order ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_place_order_disconnected_raises():
    client = make_mock_ib_client(connected=False)
    adapter = BrokerAdapter(ib_client=client, db_session_factory=AsyncMock())
    with pytest.raises(BrokerDisconnectedError):
        await adapter.place_order(make_order_request(), db=AsyncMock())


@pytest.mark.asyncio
async def test_place_order_returns_order_id():
    client = make_mock_ib_client(connected=True)

    mock_trade = MagicMock()
    mock_trade.order.orderId = 42
    client.ib.placeOrder.return_value = mock_trade

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    adapter = BrokerAdapter(ib_client=client, db_session_factory=AsyncMock())
    req = make_order_request()
    order_id_str = await adapter.place_order(req, db=mock_db)
    assert order_id_str == str(req.order_id)
    assert mock_db.commit.called


# ── pnl_snapshot_loop ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pnl_snapshot_loop_saves_to_db():
    """Verify pnl_snapshot_loop calls get_pnl_snapshot and saves to DB."""
    client = make_mock_ib_client(connected=True)

    def make_av(tag: str, value: str) -> MagicMock:
        av = MagicMock()
        av.tag = tag
        av.value = value
        av.currency = "USD"
        return av

    client.ib.reqAccountSummaryAsync = AsyncMock(return_value=[
        make_av("NetLiquidation", "100000"),
        make_av("TotalCashValue", "50000"),
        make_av("UnrealizedPnL", "500"),
        make_av("RealizedPnL", "200"),
    ])

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    adapter = BrokerAdapter(ib_client=client, db_session_factory=mock_session_factory)

    call_count = 0
    async def fake_sleep(_: float) -> None:
        nonlocal call_count
        call_count += 1
        if call_count >= 1:
            raise asyncio.CancelledError

    with patch("polara.broker.adapter.asyncio.sleep", fake_sleep):
        with pytest.raises(asyncio.CancelledError):
            await adapter.pnl_snapshot_loop()

    assert mock_db.commit.called
