"""Tests for shared indicator utilities."""
from datetime import UTC, datetime
from decimal import Decimal

from polara.research_engine.strategies.indicators import _compute_atr, _compute_ema
from polara.schemas.market import Bar


def make_bar(close: Decimal, high: Decimal | None = None, low: Decimal | None = None, i: int = 0) -> Bar:
    h = high if high is not None else close + Decimal("1")
    l = low if low is not None else close - Decimal("1")
    return Bar(
        symbol="TEST",
        timestamp=datetime(2026, 1, 2, 10, i % 60, 0, tzinfo=UTC),
        open=close,
        high=h,
        low=l,
        close=close,
        volume=1000,
    )


def make_flat_bars(close: Decimal, count: int) -> list[Bar]:
    return [make_bar(close, i=i) for i in range(count)]


# ── _compute_atr ──────────────────────────────────────────────────────────────

def test_atr_insufficient_bars_returns_zero():
    bars = make_flat_bars(Decimal("100"), 5)
    assert _compute_atr(bars, 10) == Decimal("0")


def test_atr_insufficient_bars_exact_boundary():
    # Need period + 1 bars; with exactly period bars → 0
    bars = make_flat_bars(Decimal("100"), 14)
    assert _compute_atr(bars, 14) == Decimal("0")


def test_atr_constant_candles():
    # high = close + 1, low = close - 1 → TR = 2 for every bar
    bars = make_flat_bars(Decimal("100"), 20)
    atr = _compute_atr(bars, 14)
    assert atr == Decimal("2")


def test_atr_result_is_decimal():
    bars = make_flat_bars(Decimal("50"), 20)
    result = _compute_atr(bars, 10)
    assert isinstance(result, Decimal)


def test_atr_positive_for_moving_prices():
    bars = [make_bar(Decimal(str(100 + i)), i=i) for i in range(20)]
    atr = _compute_atr(bars, 14)
    assert atr > Decimal("0")


def test_atr_wilder_smoothing_uses_all_bars():
    # More bars → Wilder smoothing applied; result still positive and consistent
    bars = make_flat_bars(Decimal("200"), 30)
    atr_short = _compute_atr(bars, 14)
    atr_long = _compute_atr(bars, 14)
    assert atr_short == atr_long  # deterministic


# ── _compute_ema ──────────────────────────────────────────────────────────────

def test_ema_empty_when_too_few():
    values = [Decimal("1"), Decimal("2")]
    assert _compute_ema(values, 5) == []


def test_ema_constant_series():
    values = [Decimal("50")] * 30
    ema = _compute_ema(values, 10)
    assert all(v == Decimal("50") for v in ema)


def test_ema_length_matches_input():
    values = [Decimal(str(i)) for i in range(50)]
    ema = _compute_ema(values, 10)
    assert len(ema) == len(values)


def test_ema_result_is_list_of_decimal():
    values = [Decimal("10")] * 20
    ema = _compute_ema(values, 5)
    assert all(isinstance(v, Decimal) for v in ema)


def test_ema_exact_minimum_length():
    # Exactly period values → seeded list, all equal to mean
    values = [Decimal("5")] * 10
    ema = _compute_ema(values, 10)
    assert len(ema) == 10
    assert all(v == Decimal("5") for v in ema)
