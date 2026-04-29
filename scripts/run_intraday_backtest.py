"""Intraday strategy backtests — ORB, VWAP MR, Gap Fill, PDH/PDL.

Fetches 30-min bars via yfinance (60 days) and runs all four new intraday
strategies across PLTR, COIN, MSTR, SMCI, RNR.  Prints a ranked results table.
"""
from datetime import UTC
from decimal import Decimal
from unittest.mock import MagicMock

import yfinance as yf

from polara.backtester.engine import Backtester
from polara.backtester.schemas import BacktestResult
from polara.research_engine.strategies.gap_fill import GapFillStrategy
from polara.research_engine.strategies.opening_range_breakout import OpeningRangeBreakoutStrategy
from polara.research_engine.strategies.prev_day_breakout import PrevDayBreakoutStrategy
from polara.research_engine.strategies.vwap_mean_reversion import VWAPMeanReversionStrategy
from polara.schemas.market import Bar

SYMBOLS = ["PLTR", "COIN", "MSTR", "SMCI", "RNR"]
BAR_SIZE = "30 mins"
PERIOD = "60d"
INTERVAL = "30m"
POSITION_SIZE_USD = Decimal("5000")


# ── Data fetching ─────────────────────────────────────────────────────────────

def fetch(symbol: str) -> list[Bar]:
    df = yf.Ticker(symbol).history(
        period=PERIOD, interval=INTERVAL, auto_adjust=True
    ).dropna()
    bars: list[Bar] = []
    for ts, row in df.iterrows():
        ts_py = ts.to_pydatetime().astimezone(UTC)
        o  = Decimal(str(round(float(row["Open"]),  10)))
        h  = Decimal(str(round(float(row["High"]),  10)))
        lo = Decimal(str(round(float(row["Low"]),   10)))
        c  = Decimal(str(round(float(row["Close"]), 10)))
        if o <= 0 or h <= 0 or lo <= 0 or c <= 0:
            continue
        bars.append(Bar(
            symbol=symbol, timestamp=ts_py,
            open=o, high=h, low=lo, close=c,
            volume=max(1, int(row["Volume"])),
        ))
    return bars


def mock_store(bars: list[Bar]) -> MagicMock:
    store = MagicMock()
    store.query.return_value = bars
    return store


# ── Backtest runner ───────────────────────────────────────────────────────────

def run(strategy, bars: list[Bar]) -> BacktestResult | None:
    store = mock_store(bars)
    try:
        return Backtester(
            strategy=strategy,
            store=store,
            position_size_usd=POSITION_SIZE_USD,
        ).run(symbol=strategy.symbol, bar_size=BAR_SIZE, lookback_bars=len(bars))
    except ValueError:
        return None


def run_all(symbol: str, bars: list[Bar]) -> list[tuple[str, BacktestResult]]:
    configs = [
        ("ORB-30m",  OpeningRangeBreakoutStrategy(
            strategy_id=f"orb-{symbol.lower()}",
            symbol=symbol,
            bar_size=BAR_SIZE,
            opening_bars=2,
            stop_buffer_pct=Decimal("0.001"),
        )),
        ("VWAP-MR",  VWAPMeanReversionStrategy(
            strategy_id=f"vwap-{symbol.lower()}",
            symbol=symbol,
            bar_size=BAR_SIZE,
            deviation_pct=Decimal("0.015"),
        )),
        ("GapFill",  GapFillStrategy(
            strategy_id=f"gap-{symbol.lower()}",
            symbol=symbol,
            bar_size=BAR_SIZE,
            min_gap_pct=Decimal("0.005"),
        )),
        ("PDH/PDL",  PrevDayBreakoutStrategy(
            strategy_id=f"pdhl-{symbol.lower()}",
            symbol=symbol,
            bar_size=BAR_SIZE,
            volume_factor=Decimal("1.5"),
        )),
    ]
    results = []
    for name, strategy in configs:
        r = run(strategy, bars)
        if r is not None:
            results.append((name, r))
    return results


# ── Formatting ────────────────────────────────────────────────────────────────

def f(d: Decimal, w: int = 6) -> str:
    return f"{float(d):>{w}.2f}"


HDR = (
    f"  {'':1} {'Symbol':<5} {'Strategy':<8}  {'Bars':>5} {'Trades':>6}"
    f"  {'Return':>7}  {'Sharpe':>6}  {'Sortino':>7}"
    f"  {'MaxDD':>6}  {'WinRate':>7}  {'PF':>5}  {'AvgPnL':>7}"
)
SEP = "─" * 96


def print_row(tick: str, symbol: str, name: str, r: BacktestResult) -> None:
    print(
        f"  {tick} {symbol:<5} {name:<8}  {r.num_bars:>5} {r.num_trades:>6}"
        f"  {f(r.total_return_pct)}%  {f(r.sharpe_ratio)}"
        f"  {f(r.sortino_ratio)}  {f(r.max_drawdown_pct)}%"
        f"  {f(r.win_rate_pct)}%  {f(r.profit_factor)}"
        f"  {f(r.avg_trade_pnl, 7)}"
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"\n{'='*96}")
    print(f"  INTRADAY STRATEGIES — 30-min bars — 60-day lookback — ${POSITION_SIZE_USD:,} position")
    print(f"  Strategies: ORB (1hr range), VWAP Mean Reversion, Gap Fill, Prev Day H/L Breakout")
    print(f"{'='*96}")
    print(HDR)
    print(SEP)

    all_results: list[tuple[str, str, BacktestResult]] = []

    for symbol in SYMBOLS:
        print(f"  Fetching {symbol} {INTERVAL} ({PERIOD})...", end=" ", flush=True)
        bars = fetch(symbol)
        print(f"{len(bars)} bars")

        rows = run_all(symbol, bars)
        for name, r in rows:
            tick = "✓" if r.passed else " "
            print_row(tick, symbol, name, r)
            all_results.append((symbol, name, r))

        print(SEP)

    # ── Passing summary, ranked by Sharpe ─────────────────────────────────────
    passing = [(s, n, r) for s, n, r in all_results if r.passed]
    passing.sort(key=lambda x: -float(x[2].sharpe_ratio))

    print(f"\n{'='*96}")
    print(f"  PASSING (Sharpe ≥ 0.5, MaxDD ≤ 20%)  —  {len(passing)} of {len(all_results)} configs")
    print(f"{'='*96}")
    if passing:
        print(HDR)
        print(SEP)
        for symbol, name, r in passing:
            print_row("✓", symbol, name, r)
    else:
        print("  (none passed — may need more data or parameter tuning)")
    print()


if __name__ == "__main__":
    main()
