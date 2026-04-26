"""BB grid search on EVGO (1h), PAYO (1d), MQ (1d).

EVGO: high retail sentiment, 7.4% daily ATR → hourly BB like PLTR
PAYO/MQ: mid-cap fintech, lower noise → daily BB
"""
from datetime import UTC
from decimal import Decimal
from unittest.mock import MagicMock

import yfinance as yf

from polara.backtester.engine import Backtester
from polara.backtester.schemas import BacktestResult
from polara.research_engine.strategies.bollinger_bands import BollingerBandStrategy
from polara.schemas.market import Bar

HOURLY_LOOKBACK = 2000
DAILY_LOOKBACK  = 1500   # ~6 years of trading days
POSITION_SIZE_USD = Decimal("120")


def fetch(symbol: str, interval: str, period: str) -> list[Bar]:
    df = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=True).dropna()
    bars = []
    for ts, row in df.iterrows():
        if hasattr(ts, "to_pydatetime"):
            ts = ts.to_pydatetime()
        ts = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)
        o = Decimal(str(round(float(row["Open"]),  10)))
        h = Decimal(str(round(float(row["High"]),  10)))
        lo = Decimal(str(round(float(row["Low"]),  10)))
        c = Decimal(str(round(float(row["Close"]), 10)))
        if o <= 0 or h <= 0 or lo <= 0 or c <= 0:
            continue
        bars.append(Bar(symbol=symbol, timestamp=ts, open=o, high=h, low=lo,
                        close=c, volume=max(1, int(row["Volume"]))))
    return bars


def bt(symbol, bars, bar_size, period, num_std) -> BacktestResult | None:
    store = MagicMock()
    store.query.return_value = bars
    s = BollingerBandStrategy(
        strategy_id=f"bb-{symbol.lower()}",
        symbol=symbol,
        period=period,
        num_std=Decimal(str(num_std)),
        quantity=Decimal("1"),
        bar_size=bar_size,
    )
    try:
        return Backtester(
            strategy=s, store=store, position_size_usd=POSITION_SIZE_USD
        ).run(symbol=symbol, bar_size=bar_size, lookback_bars=len(bars))
    except ValueError:
        return None


def fmt(d: Decimal, w: int = 6) -> str:
    return f"{float(d):>{w}.2f}"


HDR = (f"  {'':1} {'period':>6} {'std':>4}  {'Bars':>5} {'Trades':>6}"
       f"  {'Return':>7}  {'Sharpe':>6}  {'Sortino':>7}"
       f"  {'MaxDD':>6}  {'WinRate':>7}  {'PF':>5}  {'AvgPnL':>7}")
SEP = "-" * 88


def grid(symbol: str, bars: list[Bar], bar_size: str,
         periods: list[int], stds: list[float]) -> list[BacktestResult]:
    passing = []
    print(HDR)
    print(SEP)
    for p in periods:
        for std in stds:
            r = bt(symbol, bars, bar_size, p, std)
            if r is None:
                continue
            tick = "✓" if r.passed else " "
            label = f"  {tick} {p:>6} {std:>4.1f}"
            print(f"{label}  {r.num_bars:>5} {r.num_trades:>6}"
                  f"  {fmt(r.total_return_pct)}%  {fmt(r.sharpe_ratio)}"
                  f"  {fmt(r.sortino_ratio)}  {fmt(r.max_drawdown_pct)}%"
                  f"  {fmt(r.win_rate_pct)}%  {fmt(r.profit_factor)}"
                  f"  {fmt(r.avg_trade_pnl, 7)}")
            if r.passed:
                passing.append((p, std, r))
    return passing


def section(title: str) -> None:
    print(f"\n{'='*88}")
    print(f"  {title}")
    print(f"{'='*88}")


def main():
    # ── EVGO  1-hour ──────────────────────────────────────────────────────────
    section("EVGO  |  1-hour bars  |  BB grid  (period × std)")
    print(f"  Fetching EVGO 1h (730d)...", end=" ", flush=True)
    evgo = fetch("EVGO", "1h", "730d")
    evgo = evgo[-HOURLY_LOOKBACK:] if len(evgo) > HOURLY_LOOKBACK else evgo
    print(f"{len(evgo)} bars")
    evgo_pass = grid("EVGO", evgo, "1 hour",
                     periods=[10, 15, 20, 30],
                     stds=[1.5, 2.0, 2.5, 3.0])

    # ── PAYO  1-day ───────────────────────────────────────────────────────────
    section("PAYO  |  1-day bars  |  BB grid  (period × std)")
    print(f"  Fetching PAYO 1d (max)...", end=" ", flush=True)
    payo = fetch("PAYO", "1d", "max")
    payo = payo[-DAILY_LOOKBACK:] if len(payo) > DAILY_LOOKBACK else payo
    print(f"{len(payo)} bars")
    payo_pass = grid("PAYO", payo, "1 day",
                     periods=[10, 15, 20, 30, 50],
                     stds=[1.5, 2.0, 2.5, 3.0])

    # ── MQ  1-day ─────────────────────────────────────────────────────────────
    section("MQ  |  1-day bars  |  BB grid  (period × std)")
    print(f"  Fetching MQ 1d (max)...", end=" ", flush=True)
    mq = fetch("MQ", "1d", "max")
    mq = mq[-DAILY_LOOKBACK:] if len(mq) > DAILY_LOOKBACK else mq
    print(f"{len(mq)} bars")
    mq_pass = grid("MQ", mq, "1 day",
                   periods=[10, 15, 20, 30, 50],
                   stds=[1.5, 2.0, 2.5, 3.0])

    # ── Summary ───────────────────────────────────────────────────────────────
    section("PASSING CONFIGURATIONS  (Sharpe ≥ 0.5, MaxDD ≤ 20%)")
    print(f"  {'Symbol':<6}  {'period':>6} {'std':>4}  {'Bars':>5} {'Trades':>6}"
          f"  {'Return':>7}  {'Sharpe':>6}  {'Sortino':>7}"
          f"  {'MaxDD':>6}  {'WinRate':>7}  {'PF':>5}  {'AvgPnL':>7}")
    print(SEP)

    all_pass = (
        [("EVGO", p, s, r) for p, s, r in evgo_pass] +
        [("PAYO", p, s, r) for p, s, r in payo_pass] +
        [("MQ",   p, s, r) for p, s, r in mq_pass]
    )
    all_pass.sort(key=lambda x: -float(x[3].sharpe_ratio))
    for sym, p, std, r in all_pass:
        print(f"  ✓ {sym:<6}  {p:>6} {std:>4.1f}  {r.num_bars:>5} {r.num_trades:>6}"
              f"  {fmt(r.total_return_pct)}%  {fmt(r.sharpe_ratio)}"
              f"  {fmt(r.sortino_ratio)}  {fmt(r.max_drawdown_pct)}%"
              f"  {fmt(r.win_rate_pct)}%  {fmt(r.profit_factor)}"
              f"  {fmt(r.avg_trade_pnl, 7)}")
    if not all_pass:
        print("  (none)")
    print()


if __name__ == "__main__":
    main()
