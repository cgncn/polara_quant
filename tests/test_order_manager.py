"""Tests for OrderManager.process_signal()."""
from datetime import datetime, UTC
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
import pytest

from polara.broker.schemas import AccountInfo, OrderStatus, Position
from polara.order_manager.manager import OrderManager
from polara.research_engine.status_service import StrategyStatusService
from polara.risk_guard.exceptions import RiskViolationError
from polara.risk_guard.guard import RiskGuard
from polara.schemas.signals import Signal


def make_signal(symbol: str = "AAPL", strength: str = "1") -> Signal:
    return Signal(
        signal_id=uuid4(),
        strategy_id="test-strategy",
        symbol=symbol,
        strength=Decimal(strength),
        generated_at=datetime.now(UTC),
    )


def make_account() -> AccountInfo:
    return AccountInfo(
        net_liquidation=Decimal("100000"),
        cash=Decimal("50000"),
        unrealised_pnl=Decimal("0"),
        realised_pnl=Decimal("0"),
        currency="USD",
        timestamp=datetime.now(UTC),
    )


def make_order_status() -> OrderStatus:
    return OrderStatus(
        order_id=uuid4(),
        ib_order_id=None,
        status="submitted",
        submitted_at=datetime.now(UTC),
        filled_at=None,
    )


def make_mock_adapter(account=None, positions=None, order_status=None):
    adapter = AsyncMock()
    adapter.get_account = AsyncMock(return_value=account or make_account())
    adapter.get_positions = AsyncMock(return_value=positions or [])
    adapter.place_order = AsyncMock(return_value=order_status or make_order_status())
    return adapter


def make_mock_db_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    db_factory = MagicMock(return_value=session)
    return db_factory, session


def make_mock_status_service(status: str = "live") -> AsyncMock:
    svc = AsyncMock(spec=StrategyStatusService)
    svc.get_status = AsyncMock(return_value=status)
    return svc


@pytest.mark.asyncio
async def test_process_signal_buy_submits_order():
    adapter = make_mock_adapter()
    guard = RiskGuard(max_position_pct=Decimal("20"), max_daily_loss_pct=Decimal("5"))
    db_factory, session = make_mock_db_session()

    manager = OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=make_mock_status_service("live"),
    )
    result = await manager.process_signal(make_signal(strength="1"))

    assert result is not None
    assert result.status == "submitted"
    adapter.place_order.assert_called_once()
    order_req = adapter.place_order.call_args[0][0]
    assert order_req.side == "buy"
    assert order_req.symbol == "AAPL"


@pytest.mark.asyncio
async def test_process_signal_sell_on_negative_strength():
    adapter = make_mock_adapter()
    guard = RiskGuard(max_position_pct=Decimal("20"), max_daily_loss_pct=Decimal("5"))
    db_factory, session = make_mock_db_session()

    manager = OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=make_mock_status_service("live"),
    )
    result = await manager.process_signal(make_signal(strength="-1"))

    order_req = adapter.place_order.call_args[0][0]
    assert order_req.side == "sell"


@pytest.mark.asyncio
async def test_process_signal_returns_none_on_risk_violation():
    adapter = make_mock_adapter()
    mock_guard = MagicMock()
    mock_guard.check_daily_loss = MagicMock(side_effect=RiskViolationError("loss exceeded"))
    db_factory, _ = make_mock_db_session()

    manager = OrderManager(
        broker_adapter=adapter,
        risk_guard=mock_guard,
        db_session_factory=db_factory,
        status_service=make_mock_status_service("live"),
    )
    result = await manager.process_signal(make_signal())

    assert result is None
    adapter.place_order.assert_not_called()


@pytest.mark.asyncio
async def test_process_signal_writes_signal_orders_row():
    adapter = make_mock_adapter()
    guard = RiskGuard(max_position_pct=Decimal("20"), max_daily_loss_pct=Decimal("5"))
    db_factory, session = make_mock_db_session()

    manager = OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=make_mock_status_service("live"),
    )
    await manager.process_signal(make_signal())

    # Verify execute was called (signal_orders insert)
    session.execute.assert_called()
    session.commit.assert_called()


@pytest.mark.asyncio
async def test_process_signal_order_quantity_is_one():
    adapter = make_mock_adapter()
    guard = RiskGuard(max_position_pct=Decimal("20"), max_daily_loss_pct=Decimal("5"))
    db_factory, _ = make_mock_db_session()

    manager = OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=make_mock_status_service("live"),
    )
    await manager.process_signal(make_signal())

    order_req = adapter.place_order.call_args[0][0]
    assert order_req.quantity == Decimal("1")
    assert isinstance(order_req.quantity, Decimal)


@pytest.mark.asyncio
async def test_process_signal_skipped_when_status_not_live():
    """Signal from a paper/non-live strategy should be silently skipped."""
    adapter = make_mock_adapter()
    guard = RiskGuard(max_position_pct=Decimal("20"), max_daily_loss_pct=Decimal("5"))
    db_factory, _ = make_mock_db_session()

    manager = OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=make_mock_status_service("paper"),
    )
    result = await manager.process_signal(make_signal())

    assert result is None
    adapter.place_order.assert_not_called()


@pytest.mark.asyncio
async def test_process_signal_skipped_when_status_is_none():
    """Signal with no DB row (status=None) should be skipped."""
    adapter = make_mock_adapter()
    guard = RiskGuard(max_position_pct=Decimal("20"), max_daily_loss_pct=Decimal("5"))
    db_factory, _ = make_mock_db_session()

    manager = OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=make_mock_status_service(None),
    )
    result = await manager.process_signal(make_signal())

    assert result is None
    adapter.place_order.assert_not_called()


@pytest.mark.asyncio
async def test_process_signal_proceeds_when_status_is_live():
    """Signal from a live strategy should proceed through risk checks and submit."""
    adapter = make_mock_adapter()
    guard = RiskGuard(max_position_pct=Decimal("20"), max_daily_loss_pct=Decimal("5"))
    db_factory, _ = make_mock_db_session()

    manager = OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=make_mock_status_service("live"),
    )
    result = await manager.process_signal(make_signal())

    assert result is not None
    adapter.place_order.assert_called_once()


# ---------------------------------------------------------------------------
# Dynamic sizing tests
# ---------------------------------------------------------------------------

def make_signal_with_price(
    symbol: str = "AAPL",
    strength: str = "1",
    reference_price: Decimal | None = None,
) -> Signal:
    return Signal(
        signal_id=uuid4(),
        strategy_id="test-strategy",
        symbol=symbol,
        strength=Decimal(strength),
        generated_at=datetime.now(UTC),
        reference_price=reference_price,
    )


def make_account_with_nav(nav: Decimal) -> AccountInfo:
    return AccountInfo(
        net_liquidation=nav,
        cash=Decimal("0"),
        unrealised_pnl=Decimal("0"),
        realised_pnl=Decimal("0"),
        currency="USD",
        timestamp=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_dynamic_sizing_full_strength():
    """strength=1.0, NAV=100000, pct=10, price=50 → quantity=200"""
    adapter = make_mock_adapter(account=make_account_with_nav(Decimal("100000")))
    guard = RiskGuard(max_position_pct=Decimal("10"), max_daily_loss_pct=Decimal("5"))
    db_factory, _ = make_mock_db_session()

    manager = OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=make_mock_status_service("live"),
        min_order_quantity=Decimal("1"),
    )
    signal = make_signal_with_price(strength="1", reference_price=Decimal("50"))
    result = await manager.process_signal(signal)

    assert result is not None
    adapter.place_order.assert_called_once()
    req = adapter.place_order.call_args[0][0]
    assert req.quantity == Decimal("200")


@pytest.mark.asyncio
async def test_dynamic_sizing_half_strength():
    """strength=0.5, NAV=100000, pct=10, price=50 → quantity=100"""
    adapter = make_mock_adapter(account=make_account_with_nav(Decimal("100000")))
    guard = RiskGuard(max_position_pct=Decimal("10"), max_daily_loss_pct=Decimal("5"))
    db_factory, _ = make_mock_db_session()

    manager = OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=make_mock_status_service("live"),
        min_order_quantity=Decimal("1"),
    )
    signal = make_signal_with_price(strength="0.5", reference_price=Decimal("50"))
    result = await manager.process_signal(signal)

    assert result is not None
    req = adapter.place_order.call_args[0][0]
    assert req.quantity == Decimal("100")


@pytest.mark.asyncio
async def test_dynamic_sizing_no_reference_price_falls_back_to_one():
    """reference_price=None → quantity placed is Decimal('1')"""
    adapter = make_mock_adapter(account=make_account_with_nav(Decimal("100000")))
    guard = RiskGuard(max_position_pct=Decimal("10"), max_daily_loss_pct=Decimal("5"))
    db_factory, _ = make_mock_db_session()

    manager = OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=make_mock_status_service("live"),
        min_order_quantity=Decimal("1"),
    )
    signal = make_signal_with_price(strength="1", reference_price=None)
    result = await manager.process_signal(signal)

    assert result is not None
    req = adapter.place_order.call_args[0][0]
    assert req.quantity == Decimal("1")


@pytest.mark.asyncio
async def test_dynamic_sizing_below_minimum_returns_none():
    """NAV=100, pct=10, price=50, strength=1.0 → quantity=0 → returns None"""
    adapter = make_mock_adapter(account=make_account_with_nav(Decimal("100")))
    guard = RiskGuard(max_position_pct=Decimal("10"), max_daily_loss_pct=Decimal("5"))
    db_factory, _ = make_mock_db_session()

    manager = OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=make_mock_status_service("live"),
        min_order_quantity=Decimal("1"),
    )
    signal = make_signal_with_price(strength="1", reference_price=Decimal("50"))
    result = await manager.process_signal(signal)

    assert result is None
    adapter.place_order.assert_not_called()


@pytest.mark.asyncio
async def test_dynamic_sizing_custom_minimum():
    """min_order_quantity=50, computed qty=20 → returns None"""
    adapter = make_mock_adapter(account=make_account_with_nav(Decimal("100000")))
    guard = RiskGuard(max_position_pct=Decimal("10"), max_daily_loss_pct=Decimal("5"))
    db_factory, _ = make_mock_db_session()

    manager = OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=make_mock_status_service("live"),
        min_order_quantity=Decimal("50"),
    )
    # NAV=100000, pct=10, price=50, strength=0.1 → target_notional=100000*0.1*0.1=1000, qty=floor(1000/50)=20
    signal = make_signal_with_price(strength="0.1", reference_price=Decimal("50"))
    result = await manager.process_signal(signal)

    assert result is None
    adapter.place_order.assert_not_called()


@pytest.mark.asyncio
async def test_dynamic_sizing_quantity_is_decimal():
    """Quantity placed must be a Decimal instance."""
    adapter = make_mock_adapter(account=make_account_with_nav(Decimal("100000")))
    guard = RiskGuard(max_position_pct=Decimal("10"), max_daily_loss_pct=Decimal("5"))
    db_factory, _ = make_mock_db_session()

    manager = OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=make_mock_status_service("live"),
        min_order_quantity=Decimal("1"),
    )
    signal = make_signal_with_price(strength="1", reference_price=Decimal("50"))
    await manager.process_signal(signal)

    req = adapter.place_order.call_args[0][0]
    assert isinstance(req.quantity, Decimal)


@pytest.mark.asyncio
async def test_dynamic_sizing_uses_floor_not_round():
    """NAV=100000, pct=10, price=49, strength=1.0 → floor(10000/49)=204 not 205"""
    adapter = make_mock_adapter(account=make_account_with_nav(Decimal("100000")))
    guard = RiskGuard(max_position_pct=Decimal("10"), max_daily_loss_pct=Decimal("5"))
    db_factory, _ = make_mock_db_session()

    manager = OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=make_mock_status_service("live"),
        min_order_quantity=Decimal("1"),
    )
    signal = make_signal_with_price(strength="1", reference_price=Decimal("49"))
    await manager.process_signal(signal)

    req = adapter.place_order.call_args[0][0]
    assert req.quantity == Decimal("204")
