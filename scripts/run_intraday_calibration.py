"""Calibration run for passing intraday strategies.

Fetches 30-min bars via yfinance, registers passing strategies into a fresh
StrategyRegistry, runs CalibrationEngine, and prints the sizing multipliers
and best parameters found by the grid search.
"""
import asyncio
from datetime import UTC
from decimal import Decimal
from unittest.mock import MagicMock

import yfinance as yf

from polara.calibration.engine import CalibrationEngine
from polara.research_engine.registry import StrategyRegistry
from polara.research_engine.strategies.gap_fill import GapFillStrategy
from polara.research_engine.strategies.opening_range_breakout import OpeningRangeBreakoutStrategy
from polara.research_engine.strategies.prev_day_breakout import PrevDayBreakoutStrategy
from polara.research_engine.strategies.vwap_mean_reversion import VWAPMeanReversionStrategy
from polara.schemas.market import Bar

BAR_SIZE = "30 mins"
PERIOD = "60d"
INTERVAL = "30m"

# Passing configs from backtest (Sharpe ≥ 0.5, MaxDD ≤ 20%)
CONFIGS = [
    ("MSTR", "vwap",  VWAPMeanReversionStrategy),
    ("COIN", "orb",   OpeningRangeBreakoutStrategy),
    ("PLTR", "orb",   OpeningRangeBreakoutStrategy),
    ("MSTR", "pdhl",  PrevDayBreakoutStrategy),
    ("PLTR", "pdhl",  PrevDayBreakoutStrategy),
    ("MSTR", "gap",   GapFillStrategy),
    ("MSTR", "orb",   OpeningRangeBreakoutStrategy),
    ("COIN", "pdhl",  PrevDayBreakoutStrategy),
    ("COIN", "gap",   GapFillStrategy),
    ("PLTR", "gap",   GapFillStrategy),
    ("SMCI", "vwap",  VWAPMeanReversionStrategy),
    ("RNR",  "orb",   OpeningRangeBreakoutStrategy),
    ("RNR",  "gap",   GapFillStrategy),
]

DEFAULT_PARAMS = {
    VWAPMeanReversionStrategy:   {"deviation_pct": Decimal("0.015")},
    OpeningRangeBreakoutStrategy: {"opening_bars": 2, "stop_buffer_pct": Decimal("0.001")},
    PrevDayBreakoutStrategy:     {"volume_factor": Decimal("1.5")},
    GapFillStrategy:             {"min_gap_pct": Decimal("0.005")},
}


# ── yfinance helpers ──────────────────────────────────────────────────────────

_bar_cache: dict[str, list[Bar]] = {}

def fetch(symbol: str) -> list[Bar]:
    if symbol not in _bar_cache:
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
        _bar_cache[symbol] = bars
    return _bar_cache[symbol]


def mock_store_for(symbol: str) -> MagicMock:
    bars = fetch(symbol)
    store = MagicMock()
    store.query.return_value = bars
    return store


# ── Build registry ────────────────────────────────────────────────────────────

def build_registry() -> tuple[StrategyRegistry, dict[str, str]]:
    """Register all passing strategies. Returns (registry, strategy_id→symbol map)."""
    registry = StrategyRegistry()
    sid_to_symbol: dict[str, str] = {}

    for symbol, tag, cls in CONFIGS:
        params = DEFAULT_PARAMS[cls]
        sid = f"{tag}-{symbol.lower()}"
        strategy = cls(
            strategy_id=sid,
            symbol=symbol,
            bar_size=BAR_SIZE,
            **params,
        )
        registry.register(strategy)
        sid_to_symbol[sid] = symbol

    return registry, sid_to_symbol


# ── Calibration ───────────────────────────────────────────────────────────────

async def run_calibration() -> None:
    registry, sid_to_symbol = build_registry()

    # CalibrationEngine needs a single BarStore. Since each strategy uses a
    # different symbol we monkey-patch the store to dispatch by symbol.
    master_store = MagicMock()
    def smart_query(symbol, n, bar_size):
        return fetch(symbol)[-n:]
    master_store.query.side_effect = smart_query

    engine = CalibrationEngine(
        registry=registry,
        store=master_store,
        lookback_bars=780,
        position_size_usd=Decimal("5000"),
    )

    print(f"\n{'='*96}")
    print(f"  CALIBRATION RUN — 30-min bars — {len(CONFIGS)} strategies")
    print(f"{'='*96}")
    print(f"\n  {'Strategy ID':<20} {'Symbol':<6} {'Sharpe':>7}  {'Size×':>6}  "
          f"{'Param improvement':>18}  Best params")
    print("  " + "─" * 90)

    # calibrate_all takes one symbol, but our strategies span multiple symbols.
    # Call calibrate_one per strategy using the strategy's own symbol instead.
    results = []
    for strategy in registry.get_all():
        result = await asyncio.to_thread(engine.calibrate_one, strategy.strategy_id, strategy.symbol)
        if result is not None:
            results.append(result)

    for r in sorted(results, key=lambda x: -float(x.rolling_sharpe)):
        symbol = sid_to_symbol.get(r.strategy_id, "?")
        improvement = f"+{float(r.param_sharpe_improvement):.3f}" if r.param_sharpe_improvement > 0 else f" {float(r.param_sharpe_improvement):.3f}"
        best = ", ".join(f"{k}={v}" for k, v in r.best_params.items()) if r.best_params else "(unchanged)"
        print(f"  {r.strategy_id:<20} {symbol:<6} {float(r.rolling_sharpe):>7.3f}  "
              f"{float(r.size_multiplier):>5.1f}×  {improvement:>18}  {best}")

    print()

    # Size multiplier summary by tier
    tiers: dict[str, list[str]] = {"2.0×": [], "1.5×": [], "1.0×": [], "0.5×": []}
    for r in results:
        key = f"{float(r.size_multiplier):.1f}×"
        if key in tiers:
            tiers[key].append(r.strategy_id)

    print(f"  {'─'*90}")
    print(f"  Position sizing summary:")
    for tier, sids in tiers.items():
        if sids:
            print(f"    {tier}  →  {', '.join(sids)}")
    print()


if __name__ == "__main__":
    asyncio.run(run_calibration())
