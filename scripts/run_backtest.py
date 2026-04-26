"""Standalone backtest runner using yfinance historical data.

Runs all 5 strategies × 4 symbols = 20 backtests.
Uses 2000 hourly bars (~1.2 years) where available.

Usage:
    uv run python scripts/run_backtest.py
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

SYMBOLS = ["PLTR", "COIN", "SMCI", "MSTR"]
BAR_SIZE = "1 hour"
LOOKBACK_BARS = 2000
POSITION_SIZE_USD = Decimal("120")


def fetch_bars(symbol: str, n: int) -> list[Bar]:
    """Download up to n hourly bars from yfinance (max 730 days for 1h)."""
    ticker = yf.Ticker(symbol)
    # yfinance 1h bars: max period is 730 days
    df = ticker.history(period="730d", interval="1h", auto_adjust=True)
    df = df.dropna()
    bars = []
    for ts, row in df.iterrows():
        if hasattr(ts, "to_pydatetime"):
            ts = ts.to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        else:
            ts = ts.astimezone(UTC)
        o = Decimal(str(round(float(row["Open"]), 10)))
        h = Decimal(str(round(float(row["High"]), 10)))
        lo = Decimal(str(round(float(row["Low"]), 10)))
        c = Decimal(str(round(float(row["Close"]), 10)))
        vol = max(1, int(row["Volume"]))
        # Guard: all prices must be > 0
        if o <= 0 or h <= 0 or lo <= 0 or c <= 0:
            continue
        bars.append(Bar(symbol=symbol, timestamp=ts, open=o, high=h, low=lo, close=c, volume=vol))
    # Return oldest-first, trimmed to n
    return bars[-n:] if len(bars) > n else bars


def make_store(bars: list[Bar]):
    """Wrap bars in a mock BarStore."""
    store = MagicMock()
    store.query.return_value = bars
    return store


def make_strategies(symbol: str) -> list:
    return [
        MACrossoverStrategy(
            strategy_id=f"ma-crossover-{symbol.lower()}",
            symbol=symbol,
            fast_period=5,
            slow_period=20,
            quantity=Decimal("1"),
            bar_size=BAR_SIZE,
        ),
        RSIMeanReversionStrategy(
            strategy_id=f"rsi-mean-reversion-{symbol.lower()}",
            symbol=symbol,
            period=14,
            oversold=Decimal("25"),
            overbought=Decimal("75"),
            quantity=Decimal("1"),
            bar_size=BAR_SIZE,
        ),
        MACDStrategy(
            strategy_id=f"macd-{symbol.lower()}",
            symbol=symbol,
            fast_period=12,
            slow_period=26,
            signal_period=9,
            quantity=Decimal("1"),
            bar_size=BAR_SIZE,
        ),
        BollingerBandStrategy(
            strategy_id=f"bb-{symbol.lower()}",
            symbol=symbol,
            period=20,
            num_std=Decimal("2"),
            quantity=Decimal("1"),
            bar_size=BAR_SIZE,
        ),
        MomentumStrategy(
            strategy_id=f"momentum-{symbol.lower()}",
            symbol=symbol,
            period=14,
            threshold=Decimal("2"),
            quantity=Decimal("1"),
            bar_size=BAR_SIZE,
        ),
    ]


def fmt(d: Decimal, decimals: int = 2) -> str:
    return f"{float(d):.{decimals}f}"


def run() -> None:
    print(f"\n{'='*100}")
    print(f"  POLARA QUANT — BACKTEST RESULTS   ({datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')})")
    print(f"  Bar size: {BAR_SIZE}   Lookback: up to {LOOKBACK_BARS} bars (~1.2 years)")
    print(f"{'='*100}")

    header = f"{'Strategy':<32} {'Symbol':<6} {'Bars':>5} {'Trades':>6} {'Return%':>8} {'Sharpe':>7} {'Sortino':>8} {'Calmar':>7} {'MaxDD%':>7} {'WinRate%':>9} {'PF':>5} {'AvgPnL':>8} {'R:R':>6} {'PASS'}"
    print(f"\n{header}")
    print("-" * 136)

    all_results: list[tuple[str, str, BacktestResult | str]] = []

    for symbol in SYMBOLS:
        print(f"\n  Fetching {symbol} ({BAR_SIZE}, up to {LOOKBACK_BARS} bars)...", end=" ", flush=True)
        try:
            bars = fetch_bars(symbol, LOOKBACK_BARS)
            print(f"{len(bars)} bars downloaded.")
        except Exception as exc:
            print(f"FAILED: {exc}")
            for s in make_strategies(symbol):
                all_results.append((s.strategy_id, symbol, f"data fetch failed: {exc}"))
            continue

        for strategy in make_strategies(symbol):
            store = make_store(bars)
            backtester = Backtester(
                strategy=strategy, store=store, position_size_usd=POSITION_SIZE_USD
            )
            try:
                result = backtester.run(symbol=symbol, bar_size=BAR_SIZE, lookback_bars=len(bars))
                all_results.append((strategy.strategy_id, symbol, result))
            except ValueError as e:
                all_results.append((strategy.strategy_id, symbol, str(e)))

    print(f"\n{'='*100}")
    print("  RESULTS TABLE")
    print(f"{'='*100}")
    print(f"\n{header}")
    print("-" * 136)

    passing = 0
    for strategy_id, symbol, result in all_results:
        short_name = strategy_id.replace(f"-{symbol.lower()}", "")
        if isinstance(result, str):
            print(f"  {short_name:<30} {symbol:<6}  ERROR: {result}")
            continue
        r = result
        status = "✓ PASS" if r.passed else "✗ FAIL"
        if r.passed:
            passing += 1
        print(
            f"  {short_name:<30} {symbol:<6} {r.num_bars:>5} {r.num_trades:>6} "
            f"{fmt(r.total_return_pct):>8} {fmt(r.sharpe_ratio):>7} {fmt(r.sortino_ratio):>8} "
            f"{fmt(r.calmar_ratio):>7} {fmt(r.max_drawdown_pct):>7} {fmt(r.win_rate_pct):>9} "
            f"{fmt(r.profit_factor):>5} {fmt(r.avg_trade_pnl):>8} {fmt(r.reward_risk_ratio):>6}  {status}"
        )

    total = sum(1 for _, _, r in all_results if isinstance(r, BacktestResult))
    print(f"\n{'='*100}")
    print(f"  {passing}/{total} strategies passed (Sharpe ≥ 0.5 AND Max Drawdown ≤ 20%)")
    print(f"{'='*100}\n")


if __name__ == "__main__":
    run()
