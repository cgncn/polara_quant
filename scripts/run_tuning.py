"""Parameter tuning sweep.

Three investigations:
  1. RSI: loosen thresholds to 30/70 (vs current 25/75)
  2. MACD: shorter signal periods (5, 7 vs current 9)
  3. BB: grid search period × num_std across all 4 symbols
"""
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import yfinance as yf

from polara.backtester.engine import Backtester
from polara.backtester.schemas import BacktestResult
from polara.research_engine.strategies.bollinger_bands import BollingerBandStrategy
from polara.research_engine.strategies.macd import MACDStrategy
from polara.research_engine.strategies.rsi_mean_reversion import RSIMeanReversionStrategy
from polara.schemas.market import Bar

SYMBOLS = ["PLTR", "COIN", "SMCI", "MSTR"]
BAR_SIZE = "1 hour"
LOOKBACK = 2000
_bar_cache: dict[str, list[Bar]] = {}


def fetch_bars(symbol: str) -> list[Bar]:
    if symbol in _bar_cache:
        return _bar_cache[symbol]
    ticker = yf.Ticker(symbol)
    df = ticker.history(period="730d", interval="1h", auto_adjust=True).dropna()
    bars = []
    for ts, row in df.iterrows():
        if hasattr(ts, "to_pydatetime"):
            ts = ts.to_pydatetime()
        ts = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)
        o = Decimal(str(round(float(row["Open"]), 10)))
        h = Decimal(str(round(float(row["High"]), 10)))
        lo = Decimal(str(round(float(row["Low"]), 10)))
        c = Decimal(str(round(float(row["Close"]), 10)))
        if o <= 0 or h <= 0 or lo <= 0 or c <= 0:
            continue
        bars.append(Bar(symbol=symbol, timestamp=ts, open=o, high=h, low=lo,
                        close=c, volume=max(1, int(row["Volume"]))))
    result = bars[-LOOKBACK:] if len(bars) > LOOKBACK else bars
    _bar_cache[symbol] = result
    return result


def make_store(bars):
    s = MagicMock()
    s.query.return_value = bars
    return s


def backtest(strategy, bars) -> BacktestResult | None:
    try:
        return Backtester(strategy=strategy, store=make_store(bars)).run(
            symbol=strategy.symbol, bar_size=BAR_SIZE, lookback_bars=len(bars)
        )
    except ValueError:
        return None


def fmt(d: Decimal, w: int = 6) -> str:
    return f"{float(d):>{w}.2f}"


def row(label: str, sym: str, r: BacktestResult) -> str:
    status = "✓" if r.passed else " "
    return (
        f"  {status} {label:<38} {sym:<6} {r.num_bars:>5} {r.num_trades:>6}"
        f"  {fmt(r.total_return_pct)}%  {fmt(r.sharpe_ratio)}  {fmt(r.sortino_ratio)}"
        f"  {fmt(r.max_drawdown_pct)}%  {fmt(r.win_rate_pct)}%  {fmt(r.profit_factor)}  {fmt(r.avg_trade_pnl, 7)}"
    )


HDR = f"  {'':1} {'Config':<38} {'Sym':<6} {'Bars':>5} {'Trades':>6}  {'Return':>7}  {'Sharpe':>6}  {'Sortino':>7}  {'MaxDD':>6}  {'WinRate':>7}  {'PF':>6}  {'AvgPnL':>7}"
SEP = "-" * 118


def section(title: str) -> None:
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}")
    print(HDR)
    print(SEP)


def main():
    print(f"\n  Fetching data for {SYMBOLS}...", end=" ", flush=True)
    for sym in SYMBOLS:
        fetch_bars(sym)
    print("done.\n")

    # ── 1. RSI: 30/70 vs baseline 25/75 ──────────────────────────────────────
    section("1. RSI THRESHOLD COMPARISON  (period=14, baseline oversold=25/overbought=75)")
    for sym in SYMBOLS:
        bars = fetch_bars(sym)
        for oversold, overbought, label in [
            (Decimal("25"), Decimal("75"), "RSI os=25 ob=75  [baseline]"),
            (Decimal("30"), Decimal("70"), "RSI os=30 ob=70  [loosened]"),
        ]:
            s = RSIMeanReversionStrategy(
                strategy_id=f"rsi-{sym.lower()}",
                symbol=sym,
                period=14,
                oversold=oversold,
                overbought=overbought,
                quantity=Decimal("1"),
                bar_size=BAR_SIZE,
            )
            r = backtest(s, bars)
            if r:
                print(row(label, sym, r))
        print()

    # ── 2. MACD: signal period sweep ─────────────────────────────────────────
    section("2. MACD SIGNAL PERIOD SWEEP  (fast=12, slow=26)")
    for sym in SYMBOLS:
        bars = fetch_bars(sym)
        for sig in [5, 7, 9]:
            label = f"MACD sig={sig}" + ("  [baseline]" if sig == 9 else "           ")
            s = MACDStrategy(
                strategy_id=f"macd-{sym.lower()}",
                symbol=sym,
                fast_period=12,
                slow_period=26,
                signal_period=sig,
                quantity=Decimal("1"),
                bar_size=BAR_SIZE,
            )
            r = backtest(s, bars)
            if r:
                print(row(label, sym, r))
        print()

    # ── 3. BB grid: period × num_std across all symbols ──────────────────────
    section("3. BOLLINGER BAND GRID SEARCH  (period × num_std)")
    passing_bb = []
    for sym in SYMBOLS:
        bars = fetch_bars(sym)
        for period in [10, 15, 20]:
            for num_std in [Decimal("1.5"), Decimal("2.0"), Decimal("2.5")]:
                label = f"BB period={period} std={num_std}"
                if period == 20 and num_std == Decimal("2.0"):
                    label += "  [baseline]"
                s = BollingerBandStrategy(
                    strategy_id=f"bb-{sym.lower()}",
                    symbol=sym,
                    period=period,
                    num_std=num_std,
                    quantity=Decimal("1"),
                    bar_size=BAR_SIZE,
                )
                r = backtest(s, bars)
                if r:
                    print(row(label, sym, r))
                    if r.passed:
                        passing_bb.append((label, sym, r))
        print()

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print("  PASSING CONFIGURATIONS")
    print(f"{'='*80}")
    print(HDR)
    print(SEP)
    if passing_bb:
        for label, sym, r in sorted(passing_bb, key=lambda x: -float(x[2].sharpe_ratio)):
            print(row(label, sym, r))
    else:
        print("  (none)")
    print()


if __name__ == "__main__":
    main()
