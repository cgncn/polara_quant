"""Tests for GapFillStrategy."""
from datetime import UTC, datetime
from decimal import Decimal

from polara.research_engine.strategies.gap_fill import GapFillStrategy
from polara.schemas.market import Bar


def make_bar(
    price: Decimal,
    ts: datetime,
    open_price: Decimal | None = None,
) -> Bar:
    o = open_price if open_price is not None else price
    return Bar(
        symbol="AAPL",
        timestamp=ts,
        open=o,
        high=max(o, price) + Decimal("0.01"),
        low=min(o, price) - Decimal("0.01"),
        close=price,
        volume=1000,
    )


def make_strategy(**kwargs) -> GapFillStrategy:
    defaults = dict(
        strategy_id="gap-test",
        symbol="AAPL",
        bar_size="5 mins",
    )
    defaults.update(kwargs)
    return GapFillStrategy(**defaults)


# NYSE session hours for reference dates (UTC):
# 2024-03-04 open = 14:30 UTC, close = 21:00 UTC
# 2024-03-05 open = 14:30 UTC, close = 21:00 UTC

def _prev_session_bars(close: Decimal) -> list[Bar]:
    """Several bars during 2024-03-04 NYSE session."""
    times = [
        datetime(2024, 3, 4, 14, 30, tzinfo=UTC),
        datetime(2024, 3, 4, 14, 35, tzinfo=UTC),
        datetime(2024, 3, 4, 14, 40, tzinfo=UTC),
        datetime(2024, 3, 4, 14, 45, tzinfo=UTC),
    ]
    bars = [make_bar(close, t) for t in times]
    bars[-1] = make_bar(close, times[-1])
    return bars


def _today_first_bar(open_price: Decimal, close: Decimal) -> Bar:
    """First bar of 2024-03-05 session at NYSE open."""
    ts = datetime(2024, 3, 5, 14, 30, tzinfo=UTC)
    return make_bar(close, ts, open_price=open_price)


def _build_bars(prev_close: Decimal, today_open: Decimal, today_close: Decimal | None = None) -> list[Bar]:
    if today_close is None:
        today_close = today_open
    prev_bars = _prev_session_bars(prev_close)
    today_bar = _today_first_bar(today_open, today_close)
    return prev_bars + [today_bar]


# ── bars_needed ───────────────────────────────────────────────────────────────

def test_bars_needed():
    assert make_strategy().bars_needed == 20


# ── insufficient bars → None ─────────────────────────────────────────────────

def test_returns_none_fewer_than_20_bars():
    strategy = make_strategy()
    bars = _build_bars(Decimal("100"), Decimal("101"))
    assert len(bars) < 20
    assert strategy.on_bars(bars) is None


# ── today_bars edge cases ─────────────────────────────────────────────────────

def _pad_to_20(bars: list[Bar]) -> list[Bar]:
    """Prepend pre-session bars from 2024-03-03 to reach 20 total bars."""
    needed = 20 - len(bars)
    filler = [
        make_bar(Decimal("99"), datetime(2024, 3, 3, 9, i, tzinfo=UTC))
        for i in range(needed)
    ]
    return filler + bars


def test_returns_none_when_no_today_session_bar():
    strategy = make_strategy()
    prev_bars = _prev_session_bars(Decimal("100"))
    pre_session_bar = make_bar(Decimal("100"), datetime(2024, 3, 5, 10, 0, tzinfo=UTC))
    bars = _pad_to_20(prev_bars + [pre_session_bar])
    assert strategy.on_bars(bars) is None


def test_returns_none_when_second_bar_of_today():
    strategy = make_strategy()
    prev_bars = _prev_session_bars(Decimal("100"))
    today_bar1 = _today_first_bar(Decimal("101"), Decimal("101"))
    today_bar2 = make_bar(Decimal("101"), datetime(2024, 3, 5, 14, 35, tzinfo=UTC))
    bars = _pad_to_20(prev_bars + [today_bar1, today_bar2])
    assert strategy.on_bars(bars) is None


# ── gap within threshold → None ───────────────────────────────────────────────

def test_returns_none_gap_within_threshold():
    strategy = make_strategy(min_gap_pct=Decimal("0.005"))
    prev_close = Decimal("100")
    today_open = Decimal("100.4")
    bars = _pad_to_20(_build_bars(prev_close, today_open))
    assert strategy.on_bars(bars) is None


# ── gap up → sell signal ──────────────────────────────────────────────────────

def test_gap_up_returns_sell_signal():
    strategy = make_strategy(min_gap_pct=Decimal("0.005"))
    prev_close = Decimal("100")
    today_open = Decimal("101")
    bars = _pad_to_20(_build_bars(prev_close, today_open))
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.strength == Decimal("-1")


def test_gap_up_take_profit_pct_positive():
    strategy = make_strategy(min_gap_pct=Decimal("0.005"))
    prev_close = Decimal("100")
    today_open = Decimal("101")
    bars = _pad_to_20(_build_bars(prev_close, today_open))
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.take_profit_pct > Decimal("0")


def test_gap_up_stop_loss_equals_min_gap_pct():
    min_gap_pct = Decimal("0.005")
    strategy = make_strategy(min_gap_pct=min_gap_pct)
    prev_close = Decimal("100")
    today_open = Decimal("101")
    bars = _pad_to_20(_build_bars(prev_close, today_open))
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.stop_loss_pct == min_gap_pct


def test_gap_up_reference_price_is_today_open():
    strategy = make_strategy(min_gap_pct=Decimal("0.005"))
    prev_close = Decimal("100")
    today_open = Decimal("101")
    bars = _pad_to_20(_build_bars(prev_close, today_open))
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.reference_price == today_open


# ── gap down → buy signal ─────────────────────────────────────────────────────

def test_gap_down_returns_buy_signal():
    strategy = make_strategy(min_gap_pct=Decimal("0.005"))
    prev_close = Decimal("100")
    today_open = Decimal("99")
    bars = _pad_to_20(_build_bars(prev_close, today_open))
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.strength == Decimal("1")


def test_gap_down_take_profit_pct_positive():
    strategy = make_strategy(min_gap_pct=Decimal("0.005"))
    prev_close = Decimal("100")
    today_open = Decimal("99")
    bars = _pad_to_20(_build_bars(prev_close, today_open))
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.take_profit_pct > Decimal("0")


def test_gap_down_stop_loss_equals_min_gap_pct():
    min_gap_pct = Decimal("0.005")
    strategy = make_strategy(min_gap_pct=min_gap_pct)
    prev_close = Decimal("100")
    today_open = Decimal("99")
    bars = _pad_to_20(_build_bars(prev_close, today_open))
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.stop_loss_pct == min_gap_pct


# ── no previous session bars → None ──────────────────────────────────────────

def test_returns_none_no_previous_session_bars():
    strategy = make_strategy()
    today_bar = _today_first_bar(Decimal("101"), Decimal("101"))
    filler = [
        make_bar(Decimal("100"), datetime(2024, 3, 5, 10, i, tzinfo=UTC))
        for i in range(19)
    ]
    bars = filler + [today_bar]
    assert strategy.on_bars(bars) is None


# ── max_gap_pct filter ────────────────────────────────────────────────────────

def test_max_gap_pct_blocks_oversized_gap_up():
    """Gap larger than max_gap_pct (earnings-sized) → None."""
    strategy = make_strategy(min_gap_pct=Decimal("0.005"), max_gap_pct=Decimal("0.02"))
    # 5% gap-up >> max_gap_pct of 2%
    prev_close = Decimal("100")
    today_open = Decimal("105")  # 5% gap
    bars = _pad_to_20(_build_bars(prev_close, today_open))
    assert strategy.on_bars(bars) is None


def test_max_gap_pct_blocks_oversized_gap_down():
    """Large gap-down also blocked by max_gap_pct."""
    strategy = make_strategy(min_gap_pct=Decimal("0.005"), max_gap_pct=Decimal("0.02"))
    prev_close = Decimal("100")
    today_open = Decimal("95")  # 5% gap-down
    bars = _pad_to_20(_build_bars(prev_close, today_open))
    assert strategy.on_bars(bars) is None


def test_max_gap_pct_allows_gap_below_threshold():
    """Gap within (min_gap_pct, max_gap_pct] → signal produced."""
    strategy = make_strategy(min_gap_pct=Decimal("0.005"), max_gap_pct=Decimal("0.02"))
    prev_close = Decimal("100")
    today_open = Decimal("101")  # 1% gap — inside [0.5%, 2%]
    bars = _pad_to_20(_build_bars(prev_close, today_open))
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.strength == Decimal("-1")  # gap-up → sell


def test_max_gap_pct_none_allows_large_gap():
    """max_gap_pct=None (default) → no upper limit, large gaps are signalled."""
    strategy = make_strategy(min_gap_pct=Decimal("0.005"), max_gap_pct=None)
    prev_close = Decimal("100")
    today_open = Decimal("110")  # 10% gap
    bars = _pad_to_20(_build_bars(prev_close, today_open))
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.strength == Decimal("-1")


# ── PARAM_GRID ────────────────────────────────────────────────────────────────

def test_param_grid_present():
    strategy = make_strategy()
    assert hasattr(strategy, "PARAM_GRID")
    assert isinstance(strategy.PARAM_GRID, dict)
    assert len(strategy.PARAM_GRID) > 0


def test_param_grid_contains_max_gap_pct():
    strategy = make_strategy()
    assert "max_gap_pct" in strategy.PARAM_GRID
    assert "min_gap_pct" in strategy.PARAM_GRID
