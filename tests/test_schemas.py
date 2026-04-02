"""
Tests for Pydantic v2 schema validation — enforcing Decimal-only and UTC-datetime rules.
"""
from datetime import UTC, datetime, timezone, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from polara.schemas import Bar, Fill, OrderRequest, Quote, Signal, TargetPosition
from polara.schemas.events import Event, EventType


# ── Helpers ──────────────────────────────────────────────────────────────────

UTC_NOW = datetime.now(UTC)
NAIVE_DT = datetime(2026, 1, 1, 12, 0, 0)  # no tzinfo — must be rejected


def valid_bar() -> Bar:
    return Bar(
        symbol="AAPL",
        timestamp=UTC_NOW,
        open=Decimal("150.00"),
        high=Decimal("155.00"),
        low=Decimal("149.00"),
        close=Decimal("153.50"),
        volume=100_000,
    )


# ── Bar ───────────────────────────────────────────────────────────────────────

def test_bar_valid_round_trip() -> None:
    bar = valid_bar()
    assert bar.symbol == "AAPL"
    assert bar.close == Decimal("153.50")
    assert bar.volume == 100_000


def test_bar_rejects_float_price() -> None:
    with pytest.raises(ValidationError, match="Decimal"):
        Bar(
            symbol="AAPL",
            timestamp=UTC_NOW,
            open=150.0,   # float — must be rejected
            high=Decimal("155.00"),
            low=Decimal("149.00"),
            close=Decimal("153.50"),
            volume=100_000,
        )


def test_bar_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError):
        Bar(
            symbol="AAPL",
            timestamp=NAIVE_DT,  # naive — must be rejected
            open=Decimal("150.00"),
            high=Decimal("155.00"),
            low=Decimal("149.00"),
            close=Decimal("153.50"),
            volume=100_000,
        )


def test_bar_rejects_non_utc_datetime() -> None:
    eastern = datetime(2026, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=-5)))
    with pytest.raises(ValidationError):
        Bar(
            symbol="AAPL",
            timestamp=eastern,
            open=Decimal("150.00"),
            high=Decimal("155.00"),
            low=Decimal("149.00"),
            close=Decimal("153.50"),
            volume=100_000,
        )


def test_bar_rejects_zero_price() -> None:
    with pytest.raises(ValidationError):
        Bar(
            symbol="AAPL",
            timestamp=UTC_NOW,
            open=Decimal("0"),   # zero — must be rejected
            high=Decimal("155.00"),
            low=Decimal("149.00"),
            close=Decimal("153.50"),
            volume=100_000,
        )


# ── Quote ─────────────────────────────────────────────────────────────────────

def test_quote_valid() -> None:
    q = Quote(
        symbol="AAPL",
        timestamp=UTC_NOW,
        bid=Decimal("150.00"),
        ask=Decimal("150.05"),
        bid_size=100,
        ask_size=200,
    )
    assert q.ask > q.bid


def test_quote_rejects_ask_below_bid() -> None:
    with pytest.raises(ValidationError):
        Quote(
            symbol="AAPL",
            timestamp=UTC_NOW,
            bid=Decimal("150.05"),
            ask=Decimal("150.00"),  # ask < bid — invalid
            bid_size=100,
            ask_size=200,
        )


# ── OrderRequest ──────────────────────────────────────────────────────────────

def test_order_request_valid_round_trip() -> None:
    req = OrderRequest(
        order_id=uuid4(),
        symbol="AAPL",
        side="buy",
        quantity=Decimal("10"),
        limit_price=Decimal("150.00"),
        requested_at=UTC_NOW,
        strategy_id="momentum_v1",
    )
    assert req.side == "buy"
    assert req.quantity == Decimal("10")


def test_order_request_none_limit_price_allowed() -> None:
    req = OrderRequest(
        order_id=uuid4(),
        symbol="AAPL",
        side="sell",
        quantity=Decimal("5"),
        limit_price=None,
        requested_at=UTC_NOW,
        strategy_id="momentum_v1",
    )
    assert req.limit_price is None


def test_order_request_rejects_float_quantity() -> None:
    with pytest.raises(ValidationError):
        OrderRequest(
            order_id=uuid4(),
            symbol="AAPL",
            side="buy",
            quantity=10.0,  # float — must be rejected
            requested_at=UTC_NOW,
            strategy_id="momentum_v1",
        )


# ── Fill ──────────────────────────────────────────────────────────────────────

def test_fill_rejects_zero_fill_price() -> None:
    with pytest.raises(ValidationError):
        Fill(
            fill_id=uuid4(),
            order_id=uuid4(),
            symbol="AAPL",
            side="buy",
            filled_quantity=Decimal("10"),
            fill_price=Decimal("0"),  # zero — must be rejected
            commission=Decimal("1.00"),
            filled_at=UTC_NOW,
        )


def test_fill_rejects_negative_commission() -> None:
    with pytest.raises(ValidationError):
        Fill(
            fill_id=uuid4(),
            order_id=uuid4(),
            symbol="AAPL",
            side="buy",
            filled_quantity=Decimal("10"),
            fill_price=Decimal("150.00"),
            commission=Decimal("-1.00"),  # negative — must be rejected
            filled_at=UTC_NOW,
        )


# ── Signal ────────────────────────────────────────────────────────────────────

def test_signal_valid_boundary_values() -> None:
    for strength in [Decimal("-1"), Decimal("0"), Decimal("1")]:
        s = Signal(
            signal_id=uuid4(),
            strategy_id="momentum_v1",
            symbol="AAPL",
            strength=strength,
            generated_at=UTC_NOW,
        )
        assert s.strength == strength


def test_signal_rejects_strength_above_1() -> None:
    with pytest.raises(ValidationError):
        Signal(
            signal_id=uuid4(),
            strategy_id="momentum_v1",
            symbol="AAPL",
            strength=Decimal("1.001"),
            generated_at=UTC_NOW,
        )


def test_signal_rejects_strength_below_minus_1() -> None:
    with pytest.raises(ValidationError):
        Signal(
            signal_id=uuid4(),
            strategy_id="momentum_v1",
            symbol="AAPL",
            strength=Decimal("-1.001"),
            generated_at=UTC_NOW,
        )


def test_signal_rejects_float_strength() -> None:
    with pytest.raises(ValidationError):
        Signal(
            signal_id=uuid4(),
            strategy_id="momentum_v1",
            symbol="AAPL",
            strength=0.5,  # float — must be rejected
            generated_at=UTC_NOW,
        )


# ── TargetPosition ────────────────────────────────────────────────────────────

def test_target_position_rejects_weight_above_1() -> None:
    with pytest.raises(ValidationError):
        TargetPosition(
            strategy_id="momentum_v1",
            symbol="AAPL",
            target_weight=Decimal("1.001"),
            rationale="overweight",
            computed_at=UTC_NOW,
        )


def test_target_position_zero_weight_allowed() -> None:
    tp = TargetPosition(
        strategy_id="momentum_v1",
        symbol="AAPL",
        target_weight=Decimal("0"),
        rationale="flat",
        computed_at=UTC_NOW,
    )
    assert tp.target_weight == Decimal("0")
    assert tp.position_id is not None  # auto-generated UUID


# ── Event ─────────────────────────────────────────────────────────────────────

def test_event_wraps_bar_payload() -> None:
    bar = valid_bar()
    ev = Event(event_type=EventType.MARKET_DATA, payload=bar)
    assert ev.event_type == EventType.MARKET_DATA
    assert ev.payload.symbol == "AAPL"
    assert ev.event_id is not None
    assert ev.published_at.tzinfo is not None  # UTC-aware


def test_event_default_published_at_is_utc() -> None:
    bar = valid_bar()
    ev = Event(event_type=EventType.MARKET_DATA, payload=bar)
    assert ev.published_at.utcoffset() == timedelta(0)
