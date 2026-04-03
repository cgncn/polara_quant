"""Backtester engine — replay strategy on historical bars and compute metrics."""
import math
from datetime import UTC, datetime
from decimal import Decimal

from polara.backtester.schemas import BacktestResult, BacktestTrade
from polara.market_data.store import BarStore
from polara.research_engine.base import Strategy

STARTING_CAPITAL = Decimal("10000")
PASS_MIN_SHARPE = Decimal("0.5")
PASS_MAX_DRAWDOWN_PCT = Decimal("20")


def _periods_per_year(bar_size: str) -> int:
    """Approximate number of bar periods in a trading year.

    Assumes 252 trading days and 6.5 trading hours per day.
    """
    bar_size_lower = bar_size.lower()
    if "min" in bar_size_lower:
        mins = int(bar_size_lower.split()[0])
        return int(252 * 6.5 * 60 / mins)
    elif "hour" in bar_size_lower:
        hours = int(bar_size_lower.split()[0])
        return int(252 * 6.5 / hours)
    elif "day" in bar_size_lower:
        return 252
    return 252  # default fallback


def _compute_max_drawdown(equity: list[Decimal]) -> Decimal:
    """Compute maximum drawdown percentage from an equity curve."""
    if len(equity) < 2:
        return Decimal("0")
    peak = equity[0]
    max_dd = Decimal("0")
    for val in equity[1:]:
        if val > peak:
            peak = val
        if peak > Decimal("0"):
            dd = (peak - val) / peak * Decimal("100")
            if dd > max_dd:
                max_dd = dd
    return max_dd


def _compute_sharpe(equity: list[Decimal], bar_size: str) -> Decimal:
    """Compute annualised Sharpe ratio from an equity curve.

    Uses math.sqrt() at the float boundary for standard deviation and
    annualisation factor — result is immediately wrapped in Decimal(str(...)).
    """
    if len(equity) < 3:
        return Decimal("0")

    returns: list[Decimal] = []
    for i in range(1, len(equity)):
        if equity[i - 1] != Decimal("0"):
            r = (equity[i] - equity[i - 1]) / equity[i - 1]
            returns.append(r)

    if len(returns) < 2:
        return Decimal("0")

    mean_r = sum(returns, Decimal("0")) / Decimal(len(returns))
    variance = sum((r - mean_r) ** 2 for r in returns) / Decimal(len(returns) - 1)

    if variance <= Decimal("0"):
        return Decimal("0")

    # Only float boundary: math.sqrt for standard deviation.
    # Wrapped in Decimal(str(...)) to return Decimal, not float.
    std_r = Decimal(str(math.sqrt(float(variance))))

    if std_r == Decimal("0"):
        return Decimal("0")

    periods_per_year = _periods_per_year(bar_size)
    # Only float boundary: math.sqrt for annualisation factor.
    ann_factor = Decimal(str(math.sqrt(periods_per_year)))

    return mean_r / std_r * ann_factor


class Backtester:
    """Replays a strategy on historical bars and computes performance metrics."""

    def __init__(
        self,
        strategy: Strategy,
        store: BarStore,
        min_sharpe: Decimal = PASS_MIN_SHARPE,
        max_drawdown_pct: Decimal = PASS_MAX_DRAWDOWN_PCT,
    ) -> None:
        self._strategy = strategy
        self._store = store
        self._min_sharpe = min_sharpe
        self._max_drawdown_pct = max_drawdown_pct

    def run(self, *, symbol: str, bar_size: str, lookback_bars: int) -> BacktestResult:
        """Run the backtest and return a BacktestResult.

        Fills are simulated at the *open* of the bar after the signal bar.
        """
        bars = self._store.query(symbol, n=lookback_bars, bar_size=bar_size)
        # Need strategy.bars_needed bars for first signal, plus at least 1 fill bar.
        min_bars_needed = self._strategy.bars_needed + 2
        if len(bars) < min_bars_needed:
            raise ValueError(
                f"Insufficient bars: need {min_bars_needed}, got {len(bars)}"
            )

        cash = STARTING_CAPITAL
        # position = None or dict with keys side, entry_price, entry_idx
        position: dict | None = None
        equity_curve: list[Decimal] = [cash]
        trades: list[BacktestTrade] = []

        # i is the index of the last bar in the signal window.
        # bars[i+1] is the fill bar (open price used as fill).
        for i in range(self._strategy.bars_needed, len(bars) - 1):
            window = bars[: i + 1]
            signal = self._strategy.on_bars(window)
            fill_bar = bars[i + 1]
            fill_price = fill_bar.open

            if signal is not None:
                if signal.strength > Decimal("0") and position is None:
                    # Enter long position
                    position = {
                        "side": "buy",
                        "entry_price": fill_price,
                        "entry_idx": i + 1,
                    }
                elif signal.strength < Decimal("0") and position is not None:
                    # Exit long position
                    pnl = fill_price - position["entry_price"]
                    trades.append(
                        BacktestTrade(
                            entry_bar_index=position["entry_idx"],
                            exit_bar_index=i + 1,
                            side="buy",
                            entry_price=position["entry_price"],
                            exit_price=fill_price,
                            pnl=pnl,
                        )
                    )
                    cash += pnl
                    position = None

            # Mark-to-market equity at current bar close
            if position is not None:
                mtm = cash + (bars[i].close - position["entry_price"])
            else:
                mtm = cash
            equity_curve.append(mtm)

        # Close any remaining open position at the last bar's close
        if position is not None:
            last_price = bars[-1].close
            pnl = last_price - position["entry_price"]
            trades.append(
                BacktestTrade(
                    entry_bar_index=position["entry_idx"],
                    exit_bar_index=len(bars) - 1,
                    side="buy",
                    entry_price=position["entry_price"],
                    exit_price=last_price,
                    pnl=pnl,
                )
            )
            cash += pnl

        equity_curve.append(cash)

        # --- Metrics ---
        final_equity = equity_curve[-1]
        total_return_pct = (
            (final_equity - STARTING_CAPITAL) / STARTING_CAPITAL * Decimal("100")
        )

        num_trades = len(trades)
        if num_trades > 0:
            winning = sum(1 for t in trades if t.pnl > Decimal("0"))
            win_rate_pct = Decimal(winning) / Decimal(num_trades) * Decimal("100")
        else:
            win_rate_pct = Decimal("0")

        max_drawdown_pct = _compute_max_drawdown(equity_curve)
        sharpe_ratio = _compute_sharpe(equity_curve, bar_size)

        passed = (sharpe_ratio >= self._min_sharpe) and (
            max_drawdown_pct <= self._max_drawdown_pct
        )

        return BacktestResult(
            strategy_id=self._strategy.strategy_id,
            run_at=datetime.now(UTC),
            bar_size=bar_size,
            num_bars=len(bars),
            sharpe_ratio=sharpe_ratio,
            max_drawdown_pct=max_drawdown_pct,
            win_rate_pct=win_rate_pct,
            total_return_pct=total_return_pct,
            num_trades=num_trades,
            passed=passed,
        )


__all__ = [
    "Backtester",
    "STARTING_CAPITAL",
    "PASS_MIN_SHARPE",
    "PASS_MAX_DRAWDOWN_PCT",
]
