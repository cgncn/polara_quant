"""Mid-cap BB screener.

Pipeline:
  1. Universe  — S&P 400 Mid-Cap tickers from Wikipedia
  2. Bulk download — 1Y daily bars for all tickers via yfinance batch
  3. Cheap filters — price, dollar-volume, 200-SMA trend, ATR volatility
  4. Full download — 5Y daily bars for survivors only
  5. BB backtest  — grid [period × std] on each survivor
  6. Rank & report — sorted by Sharpe, passing configs highlighted

Filters applied (in order of cheapness):
  - Price > $10          (commission viability at $1/side minimum)
  - Avg daily $ vol $3M–$150M  (liquid enough to exit; small enough for inefficiency)
  - Close > SMA(200)     (not in secular downtrend — long-only mean reversion only)
  - ATR(14)% > 1.5%      (enough volatility for BB bands to be meaningful)
"""
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import numpy as np
import requests
import yfinance as yf
from bs4 import BeautifulSoup

from polara.backtester.engine import Backtester
from polara.research_engine.strategies.bollinger_bands import BollingerBandStrategy
from polara.schemas.market import Bar

# ── Config ────────────────────────────────────────────────────────────────────

FILTER_MIN_PRICE        = 10.0
FILTER_MIN_AVG_DVOL     = 3_000_000
FILTER_MAX_AVG_DVOL     = 150_000_000
FILTER_MIN_ATR_PCT      = 1.5       # ATR(14) as % of price
FILTER_ABOVE_SMA200     = True

BB_PERIODS  = [15, 20, 30]
BB_STDS     = [2.0, 2.5, 3.0]
BAR_SIZE    = "1 day"
LOOKBACK    = 1500                  # bars fed to backtester (5Y of daily ≈ 1260)

BATCH_SIZE  = 50                    # tickers per yfinance.download() call
TOP_N       = 25                    # rows in final report

# ── Step 1: Universe ──────────────────────────────────────────────────────────

def get_sp400_tickers() -> list[str]:
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"
    resp = requests.get(url, timeout=15,
                        headers={"User-Agent": "polara-screener/1.0"})
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", {"id": "constituents"})
    tickers = []
    for row in table.find_all("tr")[1:]:
        cols = row.find_all("td")
        if cols:
            ticker = cols[0].text.strip().replace(".", "-")  # BRK.B → BRK-B
            tickers.append(ticker)
    return tickers


# ── Step 2: Bulk 1Y download ──────────────────────────────────────────────────

def bulk_download_1y(tickers: list[str]) -> dict[str, object]:
    """Download 1Y of daily closes for all tickers in batches.
    Returns {ticker: DataFrame} for tickers with sufficient data."""
    frames = {}
    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i : i + BATCH_SIZE]
        print(f"  Downloading batch {i//BATCH_SIZE + 1}/{(len(tickers)-1)//BATCH_SIZE + 1}"
              f" ({len(batch)} tickers)...", end=" ", flush=True)
        raw = yf.download(
            batch, period="1y", interval="1d",
            auto_adjust=True, progress=False, threads=True,
        )
        # yfinance returns MultiIndex columns when multiple tickers
        if len(batch) == 1:
            frames[batch[0]] = raw
        else:
            for ticker in batch:
                try:
                    df = raw.xs(ticker, axis=1, level=1).dropna()
                    if len(df) >= 50:
                        frames[ticker] = df
                except (KeyError, Exception):
                    pass
        print(f"{len(frames)} loaded so far")
        time.sleep(0.3)
    return frames


# ── Step 3: Cheap filters ─────────────────────────────────────────────────────

def atr14(df) -> float:
    h = df["High"].values
    l = df["Low"].values
    c = df["Close"].values
    tr = np.maximum(h[1:] - l[1:],
         np.maximum(np.abs(h[1:] - c[:-1]),
                    np.abs(l[1:] - c[:-1])))
    return float(np.mean(tr[-14:]))


def apply_filters(frames: dict) -> list[str]:
    survivors = []
    for ticker, df in frames.items():
        try:
            close = df["Close"].values
            volume = df["Volume"].values
            last_price = float(close[-1])

            if last_price < FILTER_MIN_PRICE:
                continue

            avg_dvol = float(np.mean(close[-20:] * volume[-20:]))
            if not (FILTER_MIN_AVG_DVOL <= avg_dvol <= FILTER_MAX_AVG_DVOL):
                continue

            if len(close) >= 200 and FILTER_ABOVE_SMA200:
                sma200 = float(np.mean(close[-200:]))
                if last_price < sma200:
                    continue

            if len(close) >= 15:
                atr_pct = atr14(df) / last_price * 100
                if atr_pct < FILTER_MIN_ATR_PCT:
                    continue

            survivors.append(ticker)
        except Exception:
            continue
    return survivors


# ── Step 4: Full 5Y download ──────────────────────────────────────────────────

def download_full(ticker: str) -> list[Bar]:
    df = yf.Ticker(ticker).history(period="5y", interval="1d",
                                   auto_adjust=True).dropna()
    bars = []
    for ts, row in df.iterrows():
        if hasattr(ts, "to_pydatetime"):
            ts = ts.to_pydatetime()
        ts = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)
        o  = Decimal(str(round(float(row["Open"]),  8)))
        h  = Decimal(str(round(float(row["High"]),  8)))
        lo = Decimal(str(round(float(row["Low"]),   8)))
        c  = Decimal(str(round(float(row["Close"]), 8)))
        if o <= 0 or h <= 0 or lo <= 0 or c <= 0:
            continue
        bars.append(Bar(symbol=ticker, timestamp=ts, open=o, high=h, low=lo,
                        close=c, volume=max(1, int(row["Volume"]))))
    return bars[-LOOKBACK:] if len(bars) > LOOKBACK else bars


# ── Step 5: BB backtest grid ──────────────────────────────────────────────────

POSITION_SIZE_USD = Decimal("120")


def run_grid(ticker: str, bars: list[Bar]) -> list[dict]:
    results = []
    store = MagicMock()
    store.query.return_value = bars
    for period in BB_PERIODS:
        for std in BB_STDS:
            s = BollingerBandStrategy(
                strategy_id=f"bb-{ticker.lower()}",
                symbol=ticker,
                period=period,
                num_std=Decimal(str(std)),
                quantity=Decimal("1"),
                bar_size=BAR_SIZE,
            )
            try:
                r = Backtester(
                    strategy=s, store=store, position_size_usd=POSITION_SIZE_USD
                ).run(symbol=ticker, bar_size=BAR_SIZE, lookback_bars=len(bars))
                results.append({
                    "ticker": ticker,
                    "period": period,
                    "std": std,
                    "result": r,
                })
            except ValueError:
                pass
    return results


# ── Step 6: Report ────────────────────────────────────────────────────────────

def fmt(v: Decimal | float, w: int = 6) -> str:
    return f"{float(v):>{w}.2f}"


HDR = (f"  {'':1} {'Ticker':<7} {'p':>3} {'σ':>4}  {'Bars':>5} {'Trades':>6}"
       f"  {'Ret%':>6}  {'Sharpe':>6}  {'Sortino':>7}"
       f"  {'MaxDD%':>7}  {'WinRate%':>8}  {'PF':>5}  {'AvgPnL':>7}")
SEP = "─" * 100


def print_table(rows: list[dict], title: str) -> None:
    print(f"\n{'═'*100}")
    print(f"  {title}")
    print(f"{'═'*100}")
    print(HDR)
    print(SEP)
    for rec in rows:
        r = rec["result"]
        tick = "✓" if r.passed else " "
        print(
            f"  {tick} {rec['ticker']:<7} {rec['period']:>3} {rec['std']:>4.1f}"
            f"  {r.num_bars:>5} {r.num_trades:>6}"
            f"  {fmt(r.total_return_pct)}%  {fmt(r.sharpe_ratio)}"
            f"  {fmt(r.sortino_ratio)}  {fmt(r.max_drawdown_pct)}%"
            f"  {fmt(r.win_rate_pct)}%  {fmt(r.profit_factor)}"
            f"  {fmt(r.avg_trade_pnl, 7)}"
        )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'═'*100}")
    print(f"  POLARA QUANT — MID-CAP BB SCREENER")
    print(f"  Universe: S&P 400 Mid-Cap  |  Bar size: {BAR_SIZE}  |  {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Filters: price>${FILTER_MIN_PRICE}  |  avg$vol ${FILTER_MIN_AVG_DVOL/1e6:.0f}M–${FILTER_MAX_AVG_DVOL/1e6:.0f}M"
          f"  |  above SMA(200)  |  ATR(14)%>{FILTER_MIN_ATR_PCT}%")
    print(f"  BB grid: periods={BB_PERIODS}  stds={BB_STDS}")
    print(f"{'═'*100}\n")

    # 1. Universe
    print("── Step 1: Fetching S&P 400 tickers from Wikipedia...")
    tickers = get_sp400_tickers()
    print(f"  {len(tickers)} tickers loaded.\n")

    # 2. Bulk 1Y download
    print("── Step 2: Bulk 1Y daily download for filtering...")
    frames = bulk_download_1y(tickers)
    print(f"  {len(frames)} tickers with sufficient data.\n")

    # 3. Filters
    print("── Step 3: Applying filters...")
    survivors = apply_filters(frames)
    print(f"  {len(survivors)} survivors after filtering: {survivors}\n")

    if not survivors:
        print("  No survivors — loosen filters.")
        sys.exit(0)

    # 4 + 5. Full download + backtest
    print("── Step 4+5: Full 5Y download + BB grid backtest...")
    all_results: list[dict] = []
    for i, ticker in enumerate(survivors, 1):
        print(f"  [{i:>3}/{len(survivors)}] {ticker:<8}", end=" ", flush=True)
        bars = download_full(ticker)
        print(f"{len(bars)} bars", end=" ", flush=True)
        recs = run_grid(ticker, bars)
        best = max((r["result"].sharpe_ratio for r in recs), default=Decimal("0"))
        passing = sum(1 for r in recs if r["result"].passed)
        print(f"→ best Sharpe {float(best):.2f}  ({passing} passing configs)")
        all_results.extend(recs)
        time.sleep(0.1)

    # 6. Report
    # All results sorted by Sharpe
    all_sorted = sorted(all_results, key=lambda x: -float(x["result"].sharpe_ratio))
    passing = [r for r in all_sorted if r["result"].passed]

    print_table(all_sorted[:TOP_N], f"TOP {TOP_N} CONFIGS BY SHARPE (all survivors)")
    print_table(passing, "PASSING CONFIGS (Sharpe ≥ 0.5 AND MaxDD ≤ 20%)")

    # Best config per ticker
    print(f"\n{'═'*100}")
    print("  BEST CONFIG PER TICKER  (highest Sharpe)")
    print(f"{'═'*100}")
    print(HDR)
    print(SEP)
    seen: set[str] = set()
    for rec in all_sorted:
        t = rec["ticker"]
        if t not in seen:
            seen.add(t)
            r = rec["result"]
            tick = "✓" if r.passed else " "
            print(
                f"  {tick} {t:<7} {rec['period']:>3} {rec['std']:>4.1f}"
                f"  {r.num_bars:>5} {r.num_trades:>6}"
                f"  {fmt(r.total_return_pct)}%  {fmt(r.sharpe_ratio)}"
                f"  {fmt(r.sortino_ratio)}  {fmt(r.max_drawdown_pct)}%"
                f"  {fmt(r.win_rate_pct)}%  {fmt(r.profit_factor)}"
                f"  {fmt(r.avg_trade_pnl, 7)}"
            )

    print(f"\n  {len(passing)} passing configs across {len({r['ticker'] for r in passing})} tickers.\n")


if __name__ == "__main__":
    main()
