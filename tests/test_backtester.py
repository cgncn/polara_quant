"""Tests for the backtester engine (Backtester)."""
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from polara.backtester.engine import Backtester, STARTING_CAPITAL, IBKR_COMMISSION_MIN
from polara.backtester.schemas import BacktestResult
from polara.schemas.market import Bar
from polara.schemas.signals import Signal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_bar(
    symbol: str = "AAPL",
    close: Decimal = Decimal("100"),
    open_: Decimal | None = None,
    i: int = 0,
) -> Bar:
    price = open_ if open_ is not None else close
    return Bar(
        symbol=symbol,
        timestamp=datetime(2026, 1, (i % 28) + 1, 10, i % 60, tzinfo=UTC),
        open=price,
        high=close + Decimal("1"),
        low=close - Decimal("1"),
        close=close,
        volume=1000,
    )


def make_signal(strength: str, strategy_id: str = "test-strategy") -> Signal:
    from uuid import uuid4

    return Signal(
        signal_id=uuid4(),
        strategy_id=strategy_id,
        symbol="AAPL",
        strength=Decimal(strength),
        generated_at=datetime.now(UTC),
    )


def make_strategy(
    bars_needed: int = 5,
    symbol: str = "AAPL",
    on_bars_side_effect=None,
    on_bars_return_value=None,
) -> MagicMock:
    strategy = MagicMock()
    strategy.strategy_id = "test-strategy"
    strategy.symbol = symbol
    strategy.bars_needed = bars_needed
    strategy.bar_size = "5 mins"
    if on_bars_side_effect is not None:
        strategy.on_bars.side_effect = on_bars_side_effect
    else:
        strategy.on_bars.return_value = on_bars_return_value
    return strategy


def make_mock_store(bars: list[Bar]) -> MagicMock:
    store = MagicMock()
    store.query.return_value = bars
    return store


def make_flat_bars(n: int, price: Decimal = Decimal("100")) -> list[Bar]:
    """Return n bars all at the same price."""
    return [make_bar(close=price, open_=price, i=i) for i in range(n)]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_trades_baseline():
    """Strategy returning None for all bars → num_trades=0, win_rate=0."""
    bars = make_flat_bars(20)
    strategy = make_strategy(bars_needed=5, on_bars_return_value=None)
    result = Backtester(strategy, make_mock_store(bars)).run(
        symbol="AAPL", bar_size="5 mins", lookback_bars=20
    )

    assert result.num_trades == 0
    assert result.win_rate_pct == Decimal("0")
    assert isinstance(result, BacktestResult)


def test_single_winning_trade():
    """Buy signal at bar-index 5, sell signal at bar-index 7.

    Fill at open of bar[6] (=100) and bar[8] (=110) → gross pnl=10, win_rate=100%.
    commission_per_side=0 isolates trade mechanics from commission accounting.
    """
    prices = [Decimal("90")] * 6 + [Decimal("100")] + [Decimal("105")] + [Decimal("110")] + [Decimal("110")] * 11
    bars = [make_bar(close=prices[i], open_=prices[i], i=i) for i in range(20)]

    calls = []

    def side_effect(window):
        idx = len(window) - 1  # last bar index in window
        calls.append(idx)
        if idx == 5:
            return make_signal("0.8")   # buy
        if idx == 7:
            return make_signal("-0.8")  # sell
        return None

    strategy = make_strategy(bars_needed=5, on_bars_side_effect=side_effect)
    result = Backtester(
        strategy, make_mock_store(bars), commission_per_side=Decimal("0")
    ).run(symbol="AAPL", bar_size="5 mins", lookback_bars=20)

    assert result.num_trades == 1
    assert result.win_rate_pct == Decimal("100")
    # pnl=10 on STARTING_CAPITAL=10000 → 0.1% (no commission)
    expected_return = Decimal("10") / STARTING_CAPITAL * Decimal("100")
    assert result.total_return_pct == expected_return


def test_single_losing_trade():
    """Buy at 100, sell at 90 → gross pnl=-10, win_rate=0%."""
    prices = [Decimal("100")] * 6 + [Decimal("100")] + [Decimal("95")] + [Decimal("90")] + [Decimal("90")] * 11
    bars = [make_bar(close=prices[i], open_=prices[i], i=i) for i in range(20)]

    def side_effect(window):
        idx = len(window) - 1
        if idx == 5:
            return make_signal("0.8")
        if idx == 7:
            return make_signal("-0.8")
        return None

    strategy = make_strategy(bars_needed=5, on_bars_side_effect=side_effect)
    result = Backtester(
        strategy, make_mock_store(bars), commission_per_side=Decimal("0")
    ).run(symbol="AAPL", bar_size="5 mins", lookback_bars=20)

    assert result.num_trades == 1
    assert result.win_rate_pct == Decimal("0")
    expected_return = Decimal("-10") / STARTING_CAPITAL * Decimal("100")
    assert result.total_return_pct == expected_return


def test_fill_price_is_next_bar_open():
    """Entry price must equal the open of the bar *after* the signal bar."""
    entry_open = Decimal("123")
    prices_close = [Decimal("100")] * 20
    prices_open = [Decimal("100")] * 20
    # bar index 6 is the fill bar; its open should be the entry price
    prices_open[6] = entry_open

    bars = [
        make_bar(close=prices_close[i], open_=prices_open[i], i=i) for i in range(20)
    ]
    recorded_entry: list[Decimal] = []

    original_trade_cls = __import__(
        "polara.backtester.schemas", fromlist=["BacktestTrade"]
    ).BacktestTrade

    def side_effect(window):
        idx = len(window) - 1
        if idx == 5:
            return make_signal("0.8")   # buy; fill at bars[6].open
        if idx == 7:
            return make_signal("-0.8")  # sell
        return None

    strategy = make_strategy(bars_needed=5, on_bars_side_effect=side_effect)

    # Patch BacktestTrade to capture entry_price
    import polara.backtester.engine as engine_mod

    original_cls = engine_mod.BacktestTrade

    class CapturingTrade(original_cls):  # type: ignore[misc]
        def __init__(self, **data):
            super().__init__(**data)
            recorded_entry.append(self.entry_price)

    engine_mod.BacktestTrade = CapturingTrade  # type: ignore[assignment]
    try:
        Backtester(strategy, make_mock_store(bars)).run(
            symbol="AAPL", bar_size="5 mins", lookback_bars=20
        )
    finally:
        engine_mod.BacktestTrade = original_cls  # type: ignore[assignment]

    assert len(recorded_entry) == 1
    assert recorded_entry[0] == entry_open


def test_insufficient_bars_raises_value_error():
    """Store returns fewer bars than required → ValueError."""
    bars = make_flat_bars(3)  # bars_needed=5, min_required=7
    strategy = make_strategy(bars_needed=5)
    with pytest.raises(ValueError, match="Insufficient bars"):
        Backtester(strategy, make_mock_store(bars)).run(
            symbol="AAPL", bar_size="5 mins", lookback_bars=3
        )


def test_passed_true_when_thresholds_met():
    """Consistently rising prices → positive Sharpe and low drawdown → passed=True."""
    # 50 bars rising steadily: each bar closes $1 higher
    n = 50
    bars = [
        make_bar(close=Decimal(str(100 + i)), open_=Decimal(str(100 + i)), i=i)
        for i in range(n)
    ]

    call_count = [0]

    def side_effect(window):
        call_count[0] += 1
        # Buy on first signal opportunity, never sell
        if call_count[0] == 1:
            return make_signal("0.8")
        return None

    strategy = make_strategy(bars_needed=5, on_bars_side_effect=side_effect)
    result = Backtester(
        strategy,
        make_mock_store(bars),
        min_sharpe=Decimal("0.1"),    # low threshold so rising prices pass
        max_drawdown_pct=Decimal("50"),
    ).run(symbol="AAPL", bar_size="5 mins", lookback_bars=n)

    assert result.passed is True


def test_passed_false_when_sharpe_below_threshold():
    """All flat prices → zero returns → Sharpe=0 → passed=False."""
    bars = make_flat_bars(20)
    strategy = make_strategy(bars_needed=5, on_bars_return_value=None)
    result = Backtester(strategy, make_mock_store(bars)).run(
        symbol="AAPL", bar_size="5 mins", lookback_bars=20
    )

    assert result.sharpe_ratio == Decimal("0")
    assert result.passed is False


def test_result_fields_are_decimal():
    """Key metric fields must be Decimal instances."""
    bars = make_flat_bars(20)
    strategy = make_strategy(bars_needed=5, on_bars_return_value=None)
    result = Backtester(strategy, make_mock_store(bars)).run(
        symbol="AAPL", bar_size="5 mins", lookback_bars=20
    )

    assert isinstance(result.sharpe_ratio, Decimal)
    assert isinstance(result.max_drawdown_pct, Decimal)
    assert isinstance(result.win_rate_pct, Decimal)
    assert isinstance(result.total_return_pct, Decimal)


def test_result_run_at_is_utc():
    """result.run_at must be UTC-aware (tzinfo is not None)."""
    bars = make_flat_bars(20)
    strategy = make_strategy(bars_needed=5, on_bars_return_value=None)
    result = Backtester(strategy, make_mock_store(bars)).run(
        symbol="AAPL", bar_size="5 mins", lookback_bars=20
    )

    assert result.run_at.tzinfo is not None


def test_max_drawdown_computed_correctly():
    """Equity curve [10000, 9000, 8000, 10000] → max drawdown = 20%."""
    from polara.backtester.engine import _compute_max_drawdown

    equity = [Decimal("10000"), Decimal("9000"), Decimal("8000"), Decimal("10000")]
    dd = _compute_max_drawdown(equity)
    # Peak = 10000, trough = 8000 → drawdown = 20%
    assert dd == Decimal("20")


def test_commission_deducted_from_pnl():
    """IBKR commission ($1/side) must be deducted from trade PnL.

    Buy at 100, sell at 110 → gross pnl = $10.
    Commission: $1 entry + $1 exit = $2 round-trip.
    Net pnl = $8 → total_return = 8/10000 * 100 = 0.08%.
    Trade still counted as winning (net pnl > 0).
    """
    prices = (
        [Decimal("90")] * 6
        + [Decimal("100")]
        + [Decimal("105")]
        + [Decimal("110")]
        + [Decimal("110")] * 11
    )
    bars = [make_bar(close=prices[i], open_=prices[i], i=i) for i in range(20)]

    def side_effect(window):
        idx = len(window) - 1
        if idx == 5:
            return make_signal("0.8")
        if idx == 7:
            return make_signal("-0.8")
        return None

    strategy = make_strategy(bars_needed=5, on_bars_side_effect=side_effect)
    result = Backtester(
        strategy, make_mock_store(bars), commission_per_side=IBKR_COMMISSION_MIN
    ).run(symbol="AAPL", bar_size="5 mins", lookback_bars=20)

    # Gross $10 − $2 commission = $8 net
    net_pnl = Decimal("10") - IBKR_COMMISSION_MIN * 2
    expected_return = net_pnl / STARTING_CAPITAL * Decimal("100")
    assert result.total_return_pct == expected_return
    assert result.num_trades == 1
    assert result.win_rate_pct == Decimal("100")  # net pnl still positive


def test_commission_can_turn_winner_into_loser():
    """A small winning trade becomes a net loss after commission.

    Buy at 100, sell at 101 → gross pnl = $1.
    Round-trip commission = $2 → net pnl = -$1 → win_rate = 0%.
    """
    prices = (
        [Decimal("100")] * 6
        + [Decimal("100")]
        + [Decimal("100")]
        + [Decimal("101")]
        + [Decimal("101")] * 11
    )
    bars = [make_bar(close=prices[i], open_=prices[i], i=i) for i in range(20)]

    def side_effect(window):
        idx = len(window) - 1
        if idx == 5:
            return make_signal("0.8")
        if idx == 7:
            return make_signal("-0.8")
        return None

    strategy = make_strategy(bars_needed=5, on_bars_side_effect=side_effect)
    result = Backtester(
        strategy, make_mock_store(bars), commission_per_side=IBKR_COMMISSION_MIN
    ).run(symbol="AAPL", bar_size="5 mins", lookback_bars=20)

    # Gross $1 − $2 commission = -$1
    assert result.win_rate_pct == Decimal("0")  # net loss despite price gain
    assert result.total_return_pct < Decimal("0")
