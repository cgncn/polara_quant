"""Tests for BrokerAdapter — CPClient is mocked directly."""
import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from polara.broker.adapter import BrokerAdapter, BrokerDisconnectedError
from polara.broker.schemas import AccountInfo, BrokerStatus, PnLSnapshot, Position
from polara.schemas.orders import OrderRequest


def make_mock_cp(connected: bool = True) -> MagicMock:
    """Build a minimal mock CPClient."""
    cp = MagicMock()
    cp.connected = connected
    cp._account_id = "DU123456" if connected else None
    cp.account_id = "DU123456"
    cp.auth_status = AsyncMock(
        return_value={"authenticated": connected, "connected": connected}
    )
    cp.account_summary = AsyncMock(
        return_value={
            "netliquidation": {"amount": 0.0, "currency": "USD"},
            "totalcashvalue": {"amount": 0.0, "currency": "USD"},
            "unrealizedpnl": {"amount": 0.0, "currency": "USD"},
            "realizedpnl": {"amount": 0.0, "currency": "USD"},
        }
    )
    cp.positions = AsyncMock(return_value=[])
    cp.get_conid = AsyncMock(return_value=488867728)
    cp.place_orders = AsyncMock(
        return_value=[{"order_id": "42", "order_status": "PreSubmitted"}]
    )
    cp.cancel_order = AsyncMock(return_value={"msg": "cancelled"})
    cp.list_orders = AsyncMock(return_value={"orders": []})
    return cp


def make_mock_ib_client(connected: bool = True) -> MagicMock:
    client = MagicMock()
    client.connected = connected
    client.cp = make_mock_cp(connected)
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
    adapter = BrokerAdapter(ib_client=client, db_session_factory=AsyncMock())
    status = await adapter.get_broker_status()
    assert isinstance(status, BrokerStatus)
    assert status.connected is True


@pytest.mark.asyncio
async def test_get_broker_status_disconnected():
    client = make_mock_ib_client(connected=True)
    client.cp.auth_status = AsyncMock(side_effect=Exception("gateway error"))
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
    client.cp.account_summary = AsyncMock(
        return_value={
            "netliquidation": {"amount": 100000.0, "currency": "USD"},
            "totalcashvalue": {"amount": 50000.0, "currency": "USD"},
            "unrealizedpnl": {"amount": 500.0, "currency": "USD"},
            "realizedpnl": {"amount": 200.0, "currency": "USD"},
        }
    )
    adapter = BrokerAdapter(ib_client=client, db_session_factory=AsyncMock())
    info = await adapter.get_account()
    assert isinstance(info, AccountInfo)
    assert info.net_liquidation == Decimal("100000.0")
    assert info.cash == Decimal("50000.0")
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
    client.cp.positions = AsyncMock(
        return_value=[
            {
                "contractDesc": "AAPL",
                "position": 10.0,
                "avgCost": 150.0,
                "unrealPnl": 50.0,
            }
        ]
    )
    adapter = BrokerAdapter(ib_client=client, db_session_factory=AsyncMock())
    positions = await adapter.get_positions()
    assert len(positions) == 1
    p = positions[0]
    assert isinstance(p, Position)
    assert p.symbol == "AAPL"
    assert p.quantity == Decimal("10.0")
    assert p.avg_cost == Decimal("150.0")
    assert isinstance(p.unrealised_pnl, Decimal)


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
    client = make_mock_ib_client(connected=True)
    client.cp.account_summary = AsyncMock(
        return_value={
            "netliquidation": {"amount": 100000.0, "currency": "USD"},
            "totalcashvalue": {"amount": 50000.0, "currency": "USD"},
            "unrealizedpnl": {"amount": 500.0, "currency": "USD"},
            "realizedpnl": {"amount": 200.0, "currency": "USD"},
        }
    )

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


# ── cancel_order ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_order_not_found_raises():
    client = make_mock_ib_client(connected=True)
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)
    adapter = BrokerAdapter(ib_client=client, db_session_factory=AsyncMock())
    with pytest.raises(ValueError, match="not found"):
        await adapter.cancel_order("nonexistent-id", db=mock_db)


@pytest.mark.asyncio
async def test_cancel_order_terminal_status_raises():
    client = make_mock_ib_client(connected=True)
    mock_db = AsyncMock()
    mock_row = MagicMock()
    mock_row.status = "filled"
    mock_row.ib_order_id = 42
    mock_row.submitted_at = datetime.now(UTC).isoformat()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = mock_row
    mock_db.execute = AsyncMock(return_value=mock_result)
    adapter = BrokerAdapter(ib_client=client, db_session_factory=AsyncMock())
    with pytest.raises(ValueError, match="Cannot cancel"):
        await adapter.cancel_order("some-id", db=mock_db)


# ── place_bracket_order ───────────────────────────────────────────────────────

def make_bracket_order_req(side: str = "buy") -> OrderRequest:
    return OrderRequest(
        order_id=uuid4(),
        symbol="AAPL",
        side=side,
        quantity=Decimal("100"),
        limit_price=None,
        requested_at=datetime.now(UTC),
        strategy_id="test-strategy",
    )


@pytest.mark.asyncio
async def test_place_bracket_order_calls_place_orders_with_three():
    client = make_mock_ib_client(connected=True)
    client.cp.place_orders = AsyncMock(
        return_value=[
            {"order_id": "1"},
            {"order_id": "2"},
            {"order_id": "3"},
        ]
    )
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    adapter = BrokerAdapter(ib_client=client, db_session_factory=AsyncMock())
    req = make_bracket_order_req("buy")
    result = await adapter.place_bracket_order(
        req, stop_price=Decimal("95.00"), take_profit_price=Decimal("110.00"), db=mock_db
    )
    assert result == str(req.order_id)
    orders_sent = client.cp.place_orders.call_args[0][0]
    assert len(orders_sent) == 3
    assert orders_sent[0]["orderType"] == "MKT"
    assert orders_sent[1]["orderType"] == "STP"
    assert orders_sent[2]["orderType"] == "LMT"


@pytest.mark.asyncio
async def test_place_bracket_order_opposite_side_for_buy():
    client = make_mock_ib_client(connected=True)
    client.cp.place_orders = AsyncMock(return_value=[{"order_id": "1"}, {"order_id": "2"}, {"order_id": "3"}])
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    adapter = BrokerAdapter(ib_client=client, db_session_factory=AsyncMock())
    req = make_bracket_order_req("buy")
    await adapter.place_bracket_order(
        req, stop_price=Decimal("95.00"), take_profit_price=Decimal("110.00"), db=mock_db
    )
    orders_sent = client.cp.place_orders.call_args[0][0]
    assert orders_sent[0]["side"] == "BUY"
    assert orders_sent[1]["side"] == "SELL"
    assert orders_sent[2]["side"] == "SELL"


@pytest.mark.asyncio
async def test_place_bracket_order_opposite_side_for_sell():
    client = make_mock_ib_client(connected=True)
    client.cp.place_orders = AsyncMock(return_value=[{"order_id": "1"}, {"order_id": "2"}, {"order_id": "3"}])
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    adapter = BrokerAdapter(ib_client=client, db_session_factory=AsyncMock())
    req = make_bracket_order_req("sell")
    await adapter.place_bracket_order(
        req, stop_price=Decimal("105.00"), take_profit_price=Decimal("90.00"), db=mock_db
    )
    orders_sent = client.cp.place_orders.call_args[0][0]
    assert orders_sent[0]["side"] == "SELL"
    assert orders_sent[1]["side"] == "BUY"
    assert orders_sent[2]["side"] == "BUY"
