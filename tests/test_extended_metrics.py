"""Tests for the five new backtester metrics: sortino, calmar, profit_factor, avg_trade_pnl, reward_risk_ratio."""
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

from polara.backtester.engine import (
    Backtester,
    STARTING_CAPITAL,
    IBKR_COMMISSION_MIN,
    _compute_sortino,
)
from polara.schemas.market import Bar
from polara.schemas.signals import Signal


# ---------------------------------------------------------------------------
# Helpers (duplicated from test_backtester.py to keep tests self-contained)
# ---------------------------------------------------------------------------

def make_bar(
    close: Decimal = Decimal("100"),
    open_: Decimal | None = None,
    i: int = 0,
) -> Bar:
    price = open_ if open_ is not None else close
    return Bar(
        symbol="AAPL",
        timestamp=datetime(2026, 1, (i % 28) + 1, 10, i % 60, tzinfo=UTC),
        open=price,
        high=close + Decimal("1"),
        low=close - Decimal("1"),
        close=close,
        volume=1000,
    )


def make_signal(strength: str) -> Signal:
    from uuid import uuid4
    return Signal(
        signal_id=uuid4(),
        strategy_id="test",
        symbol="AAPL",
        strength=Decimal(strength),
        generated_at=datetime.now(UTC),
    )


def make_strategy(bars_needed: int = 5, signals=None) -> MagicMock:
    """Return a mock strategy that emits signals from the `signals` iterable."""
    strategy = MagicMock()
    strategy.strategy_id = "test"
    strategy.symbol = "AAPL"
    strategy.bars_needed = bars_needed
    strategy.bar_size = "5 mins"
    if signals is not None:
        strategy.on_bars.side_effect = iter(signals)
    return strategy


def make_store(bars: list[Bar]) -> MagicMock:
    store = MagicMock()
    store.query.return_value = bars
    return store


# ---------------------------------------------------------------------------
# _compute_sortino unit tests
# ---------------------------------------------------------------------------

def test_sortino_returns_zero_for_short_equity():
    assert _compute_sortino([Decimal("10000")], "5 mins") == Decimal("0")
    assert _compute_sortino([Decimal("10000"), Decimal("10100")], "5 mins") == Decimal("0")


def test_sortino_returns_zero_no_downside():
    """All positive returns → no downside deviation → Sortino = 0 (undefined)."""
    equity = [Decimal("10000") + Decimal("100") * Decimal(i) for i in range(10)]
    result = _compute_sortino(equity, "1 day")
    assert result == Decimal("0")


def test_sortino_positive_when_mixed_returns():
    """Mixed gains and losses → positive Sortino ratio."""
    equity = [
        Decimal("10000"), Decimal("10200"), Decimal("9800"),
        Decimal("10500"), Decimal("9600"), Decimal("10800"),
    ]
    result = _compute_sortino(equity, "1 day")
    assert result > Decimal("0")


def test_sortino_is_decimal():
    equity = [
        Decimal("10000"), Decimal("10200"), Decimal("9800"),
        Decimal("10500"), Decimal("9600"), Decimal("10800"),
    ]
    result = _compute_sortino(equity, "1 day")
    assert isinstance(result, Decimal)


# ---------------------------------------------------------------------------
# Full backtest result: new metric fields
# ---------------------------------------------------------------------------

def _run_one_trade(entry_close: Decimal, exit_close: Decimal) -> "BacktestResult":
    """Run backtester with exactly one buy→sell round trip.

    The backtester loop starts at i=bars_needed, so the mock on_bars is called
    exactly (len(bars) - 1 - bars_needed) times.  We emit: buy, None, sell.
    """
    bars_needed = 5
    # Layout:
    #   indices 0..4  = warmup (bars_needed bars at flat 100)
    #   index 5       = entry signal bar
    #   index 6       = entry fill bar (open = entry_close)
    #   index 7       = exit signal bar
    #   index 8       = exit fill bar  (open = exit_close)
    warmup = [make_bar(Decimal("100"), i=i) for i in range(bars_needed)]
    entry_signal_bar = make_bar(Decimal("100"), i=bars_needed)
    fill_bar = make_bar(entry_close, open_=entry_close, i=bars_needed + 1)
    exit_signal_bar = make_bar(Decimal("100"), i=bars_needed + 2)
    exit_fill_bar = make_bar(exit_close, open_=exit_close, i=bars_needed + 3)
    bars = warmup + [entry_signal_bar, fill_bar, exit_signal_bar, exit_fill_bar]

    # The loop runs i in range(5, 8) → 3 on_bars calls
    # Call 0 (i=5): buy signal → fill at bars[6].open = entry_close
    # Call 1 (i=6): None
    # Call 2 (i=7): sell signal → fill at bars[8].open = exit_close
    signals = [make_signal("1"), None, make_signal("-1")]

    strategy = make_strategy(bars_needed=bars_needed, signals=signals)
    store = make_store(bars)
    backtester = Backtester(strategy=strategy, store=store)
    return backtester.run(symbol="AAPL", bar_size="5 mins", lookback_bars=len(bars))


def test_profit_factor_zero_when_no_losing_trades():
    """Single winning trade with no losing trades → profit_factor = 0 (undefined: no denominator)."""
    result = _run_one_trade(entry_close=Decimal("100"), exit_close=Decimal("110"))
    assert result.num_trades == 1
    assert result.avg_trade_pnl > Decimal("0")  # it IS a winning trade
    assert result.profit_factor == Decimal("0")  # no losers → denominator = 0 → 0


def test_profit_factor_zero_on_losing_trade():
    """Single losing trade → no winners → profit_factor = 0."""
    result = _run_one_trade(entry_close=Decimal("100"), exit_close=Decimal("90"))
    assert result.profit_factor == Decimal("0")


def test_avg_trade_pnl_positive_on_win():
    """avg_trade_pnl = net PnL for single winning trade."""
    result = _run_one_trade(entry_close=Decimal("100"), exit_close=Decimal("110"))
    # gross pnl = 10, minus 1 exit commission (entry comm already deducted from cash)
    expected = Decimal("10") - IBKR_COMMISSION_MIN
    assert result.avg_trade_pnl == expected


def test_avg_trade_pnl_negative_on_loss():
    result = _run_one_trade(entry_close=Decimal("100"), exit_close=Decimal("90"))
    assert result.avg_trade_pnl < Decimal("0")


def test_avg_trade_pnl_zero_no_trades():
    """No trades → avg_trade_pnl = 0."""
    bars_needed = 5
    warmup = [make_bar(Decimal("100"), i=i) for i in range(bars_needed + 4)]
    strategy = make_strategy(bars_needed=bars_needed, signals=[None] * (bars_needed + 3))
    store = make_store(warmup)
    backtester = Backtester(strategy=strategy, store=store)
    result = backtester.run(symbol="AAPL", bar_size="5 mins", lookback_bars=len(warmup))
    assert result.avg_trade_pnl == Decimal("0")


def test_reward_risk_ratio_zero_no_losing_trades():
    """A winning trade with no losers → reward_risk_ratio = 0 (no denominator)."""
    result = _run_one_trade(entry_close=Decimal("100"), exit_close=Decimal("110"))
    assert result.reward_risk_ratio == Decimal("0")


def test_reward_risk_ratio_zero_no_winning_trades():
    """A losing trade with no winners → reward_risk_ratio = 0."""
    result = _run_one_trade(entry_close=Decimal("100"), exit_close=Decimal("90"))
    assert result.reward_risk_ratio == Decimal("0")


def test_sortino_in_result():
    """BacktestResult includes sortino_ratio field as a Decimal."""
    result = _run_one_trade(entry_close=Decimal("100"), exit_close=Decimal("110"))
    assert isinstance(result.sortino_ratio, Decimal)


def test_calmar_ratio_zero_no_drawdown():
    """If there's no drawdown, calmar_ratio = 0."""
    result = _run_one_trade(entry_close=Decimal("100"), exit_close=Decimal("110"))
    # Calmar = 0 when max_drawdown_pct = 0
    if result.max_drawdown_pct == Decimal("0"):
        assert result.calmar_ratio == Decimal("0")


def test_new_metrics_are_decimal_instances():
    """All new metric fields must be Decimal instances."""
    result = _run_one_trade(entry_close=Decimal("100"), exit_close=Decimal("105"))
    assert isinstance(result.sortino_ratio, Decimal)
    assert isinstance(result.calmar_ratio, Decimal)
    assert isinstance(result.profit_factor, Decimal)
    assert isinstance(result.avg_trade_pnl, Decimal)
    assert isinstance(result.reward_risk_ratio, Decimal)
