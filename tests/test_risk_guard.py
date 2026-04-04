"""Tests for RiskGuard pre-trade checks."""
from datetime import datetime, UTC
from decimal import Decimal
from uuid import uuid4
import pytest

from polara.risk_guard.exceptions import RiskViolationError
from polara.risk_guard.guard import RiskGuard
from polara.broker.schemas import AccountInfo, Position
from polara.schemas.signals import Signal


def make_account(
    net_liquidation: str = "100000",
    unrealised_pnl: str = "0",
    realised_pnl: str = "0",
) -> AccountInfo:
    return AccountInfo(
        net_liquidation=Decimal(net_liquidation),
        cash=Decimal("50000"),
        unrealised_pnl=Decimal(unrealised_pnl),
        realised_pnl=Decimal(realised_pnl),
        currency="USD",
        timestamp=datetime.now(UTC),
    )


def make_position(symbol: str = "AAPL", quantity: str = "10", avg_cost: str = "150.00") -> Position:
    return Position(
        symbol=symbol,
        quantity=Decimal(quantity),
        avg_cost=Decimal(avg_cost),
        unrealised_pnl=Decimal("0"),
        updated_at=datetime.now(UTC),
    )


def make_signal(symbol: str = "AAPL", strength: str = "1") -> Signal:
    return Signal(
        signal_id=uuid4(),
        strategy_id="test-strategy",
        symbol=symbol,
        strength=Decimal(strength),
        generated_at=datetime.now(UTC),
    )


def test_check_position_size_passes_within_limit():
    guard = RiskGuard(max_position_pct=Decimal("20"), max_daily_loss_pct=Decimal("5"))
    # Position: 10 shares @ $150 = $1500 notional on $100k NAV = 1.5% < 20%
    guard.check_position_size(make_signal(), [make_position()], make_account())


def test_check_position_size_raises_when_over_limit():
    guard = RiskGuard(max_position_pct=Decimal("5"), max_daily_loss_pct=Decimal("5"))
    # Position: 100 shares @ $150 = $15000 notional on $100k NAV = 15% > 5%
    with pytest.raises(RiskViolationError, match="position"):
        guard.check_position_size(make_signal(), [make_position(quantity="100")], make_account())


def test_check_position_size_no_existing_position_passes():
    guard = RiskGuard(max_position_pct=Decimal("10"), max_daily_loss_pct=Decimal("5"))
    # No existing position — always ok
    guard.check_position_size(make_signal(), [], make_account())


def test_check_daily_loss_passes_when_no_loss():
    guard = RiskGuard(max_position_pct=Decimal("10"), max_daily_loss_pct=Decimal("5"))
    guard.check_daily_loss(make_account(unrealised_pnl="100", realised_pnl="50"))


def test_check_daily_loss_raises_when_over_limit():
    guard = RiskGuard(max_position_pct=Decimal("10"), max_daily_loss_pct=Decimal("5"))
    # Loss: -$6000 on $100k NAV = 6% > 5%
    with pytest.raises(RiskViolationError, match="daily loss"):
        guard.check_daily_loss(make_account(unrealised_pnl="-6000"))


def test_check_daily_loss_halts_subsequent_calls():
    guard = RiskGuard(max_position_pct=Decimal("10"), max_daily_loss_pct=Decimal("5"))
    account = make_account(unrealised_pnl="-6000")
    with pytest.raises(RiskViolationError):
        guard.check_daily_loss(account)
    # Second call also raises — trading is halted
    with pytest.raises(RiskViolationError, match="halted"):
        guard.check_daily_loss(make_account())


def test_check_position_size_raises_when_halted():
    guard = RiskGuard(max_position_pct=Decimal("10"), max_daily_loss_pct=Decimal("5"))
    with pytest.raises(RiskViolationError):
        guard.check_daily_loss(make_account(unrealised_pnl="-6000"))
    with pytest.raises(RiskViolationError, match="halted"):
        guard.check_position_size(make_signal(), [], make_account())


def test_risk_violation_error_is_exception():
    err = RiskViolationError("test message")
    assert isinstance(err, Exception)
    assert str(err) == "test message"


def test_max_position_pct_property_exposed():
    guard = RiskGuard(max_position_pct=Decimal("10"), max_daily_loss_pct=Decimal("5"))
    assert guard.max_position_pct == Decimal("10")
