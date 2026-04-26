"""Grand backtest — all strategy variants × all symbols × both bar sizes.

Runs 10 strategy variants × 10 symbols = up to 100 backtests.
Hourly: MA, RSI, MACD, BB(20/2.0), Momentum  — 5 variants × 10 symbols
Daily:  BB(30/2.0), BB(15/2.0), MA, MACD, Momentum — 5 variants × 10 symbols

Usage:
    uv run python scripts/run_grand_backtest.py
"""
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import yfinance as yf

from polara.backtester.engine import Backtester
from polara.backtester.schemas import BacktestResult
from polara.research_engine.strategies.bollinger_bands import BollingerBandStrategy
from polara.research_engine.strategies.ma_crossover import MACrossoverStrategy
from polara.research_engine.strategies.macd import MACDStrategy
from polara.research_engine.strategies.momentum import MomentumStrategy
from polara.research_engine.strategies.rsi_mean_reversion import RSIMeanReversionStrategy
from polara.schemas.market import Bar

HOURLY_SYMBOLS = ["PLTR", "COIN", "SMCI", "MSTR", "EVGO"]
DAILY_SYMBOLS  = ["PAYO", "MQ", "AM", "RNR", "CSL"]
ALL_SYMBOLS    = HOURLY_SYMBOLS + DAILY_SYMBOLS

HOURLY_LOOKBACK   = 2000
DAILY_LOOKBACK    = 1500
POSITION_SIZE_USD = Decimal("120")

HEADER = (
    f"  {'Strategy':<20} {'Symbol':<6} {'Bar':>3} {'Bars':>5} {'Trades':>6}"
    f" {'Return%':>8} {'Sharpe':>7} {'Sortino':>8} {'Calmar':>7}"
    f" {'MaxDD%':>7} {'WinRate%':>9} {'PF':>5} {'AvgPnL':>8} {'R:R':>6}  PASS"
)
SEP = "-" * 160


def fetch_hourly(symbol: str) -> list[Bar]:
    """Download up to HOURLY_LOOKBACK 1h bars (yfinance max period=730d)."""
    df = yf.Ticker(symbol).history(period="730d", interval="1h", auto_adjust=True).dropna()
    bars = []
    for ts, row in df.iterrows():
        if hasattr(ts, "to_pydatetime"):
            ts = ts.to_pydatetime()
        ts = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)
        o  = Decimal(str(round(float(row["Open"]),  10)))
        h  = Decimal(str(round(float(row["High"]),  10)))
        lo = Decimal(str(round(float(row["Low"]),   10)))
        c  = Decimal(str(round(float(row["Close"]), 10)))
        if o <= 0 or h <= 0 or lo <= 0 or c <= 0:
            continue
        bars.append(Bar(symbol=symbol, timestamp=ts, open=o, high=h,
                        low=lo, close=c, volume=max(1, int(row["Volume"]))))
    return bars[-HOURLY_LOOKBACK:] if len(bars) > HOURLY_LOOKBACK else bars


def fetch_daily(symbol: str) -> list[Bar]:
    """Download up to DAILY_LOOKBACK 1d bars (yfinance period=max)."""
    df = yf.Ticker(symbol).history(period="max", interval="1d", auto_adjust=True).dropna()
    bars = []
    for ts, row in df.iterrows():
        if hasattr(ts, "to_pydatetime"):
            ts = ts.to_pydatetime()
        ts = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)
        o  = Decimal(str(round(float(row["Open"]),  10)))
        h  = Decimal(str(round(float(row["High"]),  10)))
        lo = Decimal(str(round(float(row["Low"]),   10)))
        c  = Decimal(str(round(float(row["Close"]), 10)))
        if o <= 0 or h <= 0 or lo <= 0 or c <= 0:
            continue
        bars.append(Bar(symbol=symbol, timestamp=ts, open=o, high=h,
                        low=lo, close=c, volume=max(1, int(row["Volume"]))))
    return bars[-DAILY_LOOKBACK:] if len(bars) > DAILY_LOOKBACK else bars


def make_store(bars: list[Bar]):
    store = MagicMock()
    store.query.return_value = bars
    return store


def fmt(d: Decimal, decimals: int = 2) -> str:
    return f"{float(d):.{decimals}f}"


def print_row(label: str, symbol: str, bar_label: str, r: BacktestResult) -> None:
    tick   = "+" if r.passed else " "
    status = "PASS" if r.passed else "FAIL"
    print(
        f"  {tick} {label:<19} {symbol:<6} {bar_label:>3} {r.num_bars:>5} {r.num_trades:>6}"
        f" {fmt(r.total_return_pct):>8} {fmt(r.sharpe_ratio):>7} {fmt(r.sortino_ratio):>8}"
        f" {fmt(r.calmar_ratio):>7} {fmt(r.max_drawdown_pct):>7} {fmt(r.win_rate_pct):>9}"
        f" {fmt(r.profit_factor):>5} {fmt(r.avg_trade_pnl):>8} {fmt(r.reward_risk_ratio):>6}"
        f"  {status}"
    )


def make_hourly_strategies(symbol: str) -> list:
    bs = "1 hour"
    sym = symbol.lower()
    return [
        MACrossoverStrategy(
            strategy_id=f"h-ma-{sym}", symbol=symbol,
            fast_period=5, slow_period=20,
            quantity=Decimal("1"), bar_size=bs,
        ),
        RSIMeanReversionStrategy(
            strategy_id=f"h-rsi-{sym}", symbol=symbol,
            period=14, oversold=Decimal("25"), overbought=Decimal("75"),
            quantity=Decimal("1"), bar_size=bs,
        ),
        MACDStrategy(
            strategy_id=f"h-macd-{sym}", symbol=symbol,
            fast_period=12, slow_period=26, signal_period=9,
            quantity=Decimal("1"), bar_size=bs,
        ),
        BollingerBandStrategy(
            strategy_id=f"h-bb20-{sym}", symbol=symbol,
            period=20, num_std=Decimal("2"),
            quantity=Decimal("1"), bar_size=bs,
        ),
        MomentumStrategy(
            strategy_id=f"h-mom-{sym}", symbol=symbol,
            period=14, threshold=Decimal("2"),
            quantity=Decimal("1"), bar_size=bs,
        ),
    ]


def make_daily_strategies(symbol: str) -> list:
    bs = "1 day"
    sym = symbol.lower()
    return [
        BollingerBandStrategy(
            strategy_id=f"d-bb30-{sym}", symbol=symbol,
            period=30, num_std=Decimal("2"),
            quantity=Decimal("1"), bar_size=bs,
        ),
        BollingerBandStrategy(
            strategy_id=f"d-bb15-{sym}", symbol=symbol,
            period=15, num_std=Decimal("2"),
            quantity=Decimal("1"), bar_size=bs,
        ),
        MACrossoverStrategy(
            strategy_id=f"d-ma-{sym}", symbol=symbol,
            fast_period=5, slow_period=20,
            quantity=Decimal("1"), bar_size=bs,
        ),
        MACDStrategy(
            strategy_id=f"d-macd-{sym}", symbol=symbol,
            fast_period=12, slow_period=26, signal_period=9,
            quantity=Decimal("1"), bar_size=bs,
        ),
        MomentumStrategy(
            strategy_id=f"d-mom-{sym}", symbol=symbol,
            period=14, threshold=Decimal("2"),
            quantity=Decimal("1"), bar_size=bs,
        ),
    ]


def run_strategies(
    symbol: str,
    bars: list[Bar],
    strategies: list,
    bar_size: str,
    bar_label: str,
    all_results: list,
) -> None:
    for strategy in strategies:
        label = strategy.strategy_id.replace(f"-{symbol.lower()}", "")
        store = make_store(bars)
        backtester = Backtester(
            strategy=strategy, store=store, position_size_usd=POSITION_SIZE_USD
        )
        try:
            result = backtester.run(
                symbol=symbol, bar_size=bar_size, lookback_bars=len(bars)
            )
            all_results.append((label, symbol, bar_label, result))
            print_row(label, symbol, bar_label, result)
        except ValueError as e:
            all_results.append((label, symbol, bar_label, str(e)))
            print(f"    {label:<20} {symbol:<6} {bar_label}  ERROR: {e}")


def run() -> None:
    now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    width = 90
    print(f"\n{'='*width}")
    print(f"  POLARA QUANT — GRAND BACKTEST   ({now_str})")
    print(f"  10 strategy variants × 10 symbols = up to 100 backtests")
    print(f"  Starting capital: $10,000   Position size: ${POSITION_SIZE_USD}")
    print(f"{'='*width}")

    all_results: list[tuple[str, str, str, BacktestResult | str]] = []

    # ── HOURLY BACKTESTS ──────────────────────────────────────────────────────
    print(f"\n{'='*width}")
    print(f"  HOURLY BACKTESTS  (MA, RSI, MACD, BB-20/2σ, Momentum  ×  10 symbols, 1h bars)")
    print(f"{'='*width}")
    print(f"\n{HEADER}")
    print(SEP)

    for symbol in ALL_SYMBOLS:
        print(f"\n  Fetching {symbol} (1h, up to {HOURLY_LOOKBACK} bars)...",
              end=" ", flush=True)
        try:
            bars = fetch_hourly(symbol)
            print(f"{len(bars)} bars.")
        except Exception as exc:
            print(f"FAILED: {exc}")
            for s in make_hourly_strategies(symbol):
                label = s.strategy_id.replace(f"-{symbol.lower()}", "")
                all_results.append((label, symbol, "1h", f"fetch failed: {exc}"))
            continue
        run_strategies(symbol, bars, make_hourly_strategies(symbol),
                       "1 hour", "1h", all_results)

    # ── DAILY BACKTESTS ───────────────────────────────────────────────────────
    print(f"\n\n{'='*width}")
    print(f"  DAILY BACKTESTS  (BB-30/2σ, BB-15/2σ, MA, MACD, Momentum  ×  10 symbols, 1d bars)")
    print(f"{'='*width}")
    print(f"\n{HEADER}")
    print(SEP)

    for symbol in ALL_SYMBOLS:
        print(f"\n  Fetching {symbol} (1d, max)...", end=" ", flush=True)
        try:
            bars = fetch_daily(symbol)
            print(f"{len(bars)} bars.")
        except Exception as exc:
            print(f"FAILED: {exc}")
            for s in make_daily_strategies(symbol):
                label = s.strategy_id.replace(f"-{symbol.lower()}", "")
                all_results.append((label, symbol, "1d", f"fetch failed: {exc}"))
            continue
        run_strategies(symbol, bars, make_daily_strategies(symbol),
                       "1 day", "1d", all_results)

    # ── GRAND SUMMARY ─────────────────────────────────────────────────────────
    valid = [
        (lbl, sym, bar_lbl, r)
        for lbl, sym, bar_lbl, r in all_results
        if isinstance(r, BacktestResult)
    ]
    errors = [
        (lbl, sym, bar_lbl, r)
        for lbl, sym, bar_lbl, r in all_results
        if isinstance(r, str)
    ]
    valid_sorted = sorted(valid, key=lambda x: float(x[3].sharpe_ratio), reverse=True)

    print(f"\n\n{'='*width}")
    print("  GRAND SUMMARY — ALL RESULTS  (sorted by Sharpe ratio, descending)")
    print(f"{'='*width}")
    print(f"\n{HEADER}")
    print(SEP)

    passing = 0
    for lbl, sym, bar_lbl, r in valid_sorted:
        if r.passed:
            passing += 1
        print_row(lbl, sym, bar_lbl, r)

    if errors:
        print(f"\n  --- {len(errors)} error(s) excluded from ranking ---")
        for lbl, sym, bar_lbl, msg in errors:
            print(f"    {lbl:<20} {sym:<6} {bar_lbl}  {msg}")

    # ── TOP 10 ────────────────────────────────────────────────────────────────
    print(f"\n\n{'='*width}")
    print("  TOP 10 CONFIGURATIONS BY SHARPE RATIO")
    print(f"{'='*width}")
    print(f"\n{HEADER}")
    print(SEP)

    for lbl, sym, bar_lbl, r in valid_sorted[:10]:
        print_row(lbl, sym, bar_lbl, r)

    # ── FOOTER ────────────────────────────────────────────────────────────────
    total_valid = len(valid)
    print(f"\n{'='*width}")
    print(f"  {passing}/{total_valid} backtests passed  (Sharpe >= 0.5 AND MaxDD <= 20%)")
    if errors:
        print(f"  {len(errors)} backtests skipped (data fetch failure or insufficient bars)")
    print(f"{'='*width}\n")


if __name__ == "__main__":
    run()
