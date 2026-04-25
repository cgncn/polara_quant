"""Backtester schemas — BacktestTrade and BacktestResult."""
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict


class BacktestTrade(BaseModel):
    model_config = ConfigDict(strict=True)

    entry_bar_index: int
    exit_bar_index: int
    side: Literal["buy", "sell"]
    entry_price: Decimal
    exit_price: Decimal
    pnl: Decimal  # (exit_price - entry_price) * direction, expressed in Decimal


class BacktestResult(BaseModel):
    model_config = ConfigDict(strict=True)

    strategy_id: str
    run_at: datetime  # UTC-aware
    bar_size: str
    num_bars: int
    sharpe_ratio: Decimal
    max_drawdown_pct: Decimal  # 0–100
    win_rate_pct: Decimal      # 0–100
    total_return_pct: Decimal  # can be negative
    num_trades: int
    passed: bool
    # Extended metrics
    sortino_ratio: Decimal = Decimal("0")       # Sharpe using downside deviation only
    calmar_ratio: Decimal = Decimal("0")        # annualised return / max drawdown
    profit_factor: Decimal = Decimal("0")       # gross profit / gross loss (0 = no losers)
    avg_trade_pnl: Decimal = Decimal("0")       # mean net PnL per trade
    reward_risk_ratio: Decimal = Decimal("0")   # avg winner / avg loser (0 = no losers)
    notes: str | None = None


__all__ = ["BacktestTrade", "BacktestResult"]
