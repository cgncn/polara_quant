"""Unit tests for OrderManager._compute_exit_prices."""
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from polara.order_manager.manager import OrderManager
from polara.risk_guard.guard import RiskGuard
from polara.schemas.signals import Signal


def make_manager() -> OrderManager:
    adapter = MagicMock()
    guard = RiskGuard(max_position_pct=Decimal("10"), max_daily_loss_pct=Decimal("5"))
    db_factory = MagicMock()
    status_service = AsyncMock()
    return OrderManager(
        broker_adapter=adapter,
        risk_guard=guard,
        db_session_factory=db_factory,
        status_service=status_service,
    )


def make_signal(
    stop_loss_pct: Decimal | None = None,
    take_profit_pct: Decimal | None = None,
    reference_price: Decimal | None = None,
) -> Signal:
    return Signal(
        signal_id=uuid4(),
        strategy_id="s1",
        symbol="AAPL",
        strength=Decimal("1"),
        generated_at=datetime.now(UTC),
        reference_price=reference_price,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
    )


def test_stop_price_buy_signal():
    om = make_manager()
    sig = make_signal(stop_loss_pct=Decimal("5"), reference_price=Decimal("100"))
    stop, tp = om._compute_exit_prices(sig, "buy")
    assert stop == Decimal("95.00")
    assert tp is None


def test_take_profit_buy_signal():
    om = make_manager()
    sig = make_signal(take_profit_pct=Decimal("10"), reference_price=Decimal("100"))
    stop, tp = om._compute_exit_prices(sig, "buy")
    assert stop is None
    assert tp == Decimal("110.00")


def test_stop_price_sell_signal():
    om = make_manager()
    sig = make_signal(stop_loss_pct=Decimal("5"), reference_price=Decimal("100"))
    stop, tp = om._compute_exit_prices(sig, "sell")
    assert stop == Decimal("105.00")


def test_take_profit_sell_signal():
    om = make_manager()
    sig = make_signal(take_profit_pct=Decimal("10"), reference_price=Decimal("100"))
    stop, tp = om._compute_exit_prices(sig, "sell")
    assert tp == Decimal("90.00")


def test_exit_prices_none_when_no_reference_price():
    om = make_manager()
    sig = make_signal(
        stop_loss_pct=Decimal("5"),
        take_profit_pct=Decimal("10"),
        reference_price=None,
    )
    stop, tp = om._compute_exit_prices(sig, "buy")
    assert stop is None
    assert tp is None


def test_exit_prices_none_when_no_pct_set():
    om = make_manager()
    sig = make_signal(reference_price=Decimal("100"))
    stop, tp = om._compute_exit_prices(sig, "buy")
    assert stop is None
    assert tp is None


def test_stop_price_rounded_to_cents():
    om = make_manager()
    sig = make_signal(stop_loss_pct=Decimal("5"), reference_price=Decimal("100.005"))
    stop, _ = om._compute_exit_prices(sig, "buy")
    assert stop is not None
    assert stop == stop.quantize(Decimal("0.01"))
