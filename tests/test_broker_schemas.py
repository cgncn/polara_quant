"""Tests for broker-specific Pydantic schemas."""
from decimal import Decimal
from datetime import datetime, UTC
from uuid import uuid4
import pytest
from pydantic import ValidationError

from polara.broker.schemas import (
    AccountInfo,
    Position,
    PnLSnapshot,
    BrokerStatus,
    OrderStatus,
    OrderWithFills,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


# ── AccountInfo ────────────────────────────────────────────────────────────────

def test_account_info_valid():
    a = AccountInfo(
        net_liquidation=Decimal("100000.00"),
        cash=Decimal("50000.00"),
        unrealised_pnl=Decimal("500.00"),
        realised_pnl=Decimal("200.00"),
        currency="USD",
        timestamp=utcnow(),
    )
    assert a.net_liquidation == Decimal("100000.00")


def test_account_info_rejects_float():
    with pytest.raises(ValidationError):
        AccountInfo(
            net_liquidation=100000.0,  # float — must be rejected
            cash=Decimal("50000.00"),
            unrealised_pnl=Decimal("0"),
            realised_pnl=Decimal("0"),
            currency="USD",
            timestamp=utcnow(),
        )


def test_account_info_rejects_naive_datetime():
    from datetime import datetime
    with pytest.raises(ValidationError):
        AccountInfo(
            net_liquidation=Decimal("100000"),
            cash=Decimal("50000"),
            unrealised_pnl=Decimal("0"),
            realised_pnl=Decimal("0"),
            currency="USD",
            timestamp=datetime(2026, 1, 1),  # naive — must be rejected
        )


# ── Position ───────────────────────────────────────────────────────────────────

def test_position_valid():
    p = Position(
        symbol="AAPL",
        quantity=Decimal("10"),
        avg_cost=Decimal("150.00"),
        unrealised_pnl=Decimal("50.00"),
        updated_at=utcnow(),
    )
    assert p.symbol == "AAPL"


def test_position_rejects_float_quantity():
    with pytest.raises(ValidationError):
        Position(
            symbol="AAPL",
            quantity=10.0,  # float — must be rejected
            avg_cost=Decimal("150.00"),
            unrealised_pnl=Decimal("0"),
            updated_at=utcnow(),
        )


# ── PnLSnapshot ────────────────────────────────────────────────────────────────

def test_pnl_snapshot_valid():
    s = PnLSnapshot(
        net_liquidation=Decimal("100000"),
        cash=Decimal("50000"),
        unrealised_pnl=Decimal("500"),
        realised_pnl=Decimal("200"),
        snapshot_at=utcnow(),
    )
    assert s.snapshot_at.tzinfo is not None


# ── BrokerStatus ───────────────────────────────────────────────────────────────

def test_broker_status_connected():
    s = BrokerStatus(connected=True, ib_server_time=utcnow(), account_id="DU123456")
    assert s.connected is True


def test_broker_status_disconnected():
    s = BrokerStatus(connected=False, ib_server_time=None, account_id=None)
    assert s.ib_server_time is None


# ── OrderStatus ────────────────────────────────────────────────────────────────

def test_order_status_valid():
    s = OrderStatus(
        order_id=uuid4(),
        ib_order_id=42,
        status="submitted",
        submitted_at=utcnow(),
        filled_at=None,
    )
    assert s.status == "submitted"


def test_order_status_rejects_invalid_status():
    with pytest.raises(ValidationError):
        OrderStatus(
            order_id=uuid4(),
            ib_order_id=None,
            status="flying",  # not a valid status
            submitted_at=utcnow(),
            filled_at=None,
        )


# ── OrderWithFills ─────────────────────────────────────────────────────────────

def test_order_with_fills_empty():
    from polara.schemas.orders import Fill, OrderSide
    o = OrderWithFills(
        order_id=uuid4(),
        ib_order_id=None,
        status="pending",
        submitted_at=utcnow(),
        filled_at=None,
        fills=[],
    )
    assert o.fills == []
