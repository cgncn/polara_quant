"""Strategy REST endpoints — manual trigger, listing, validation, and promotion."""
import asyncio
import logging
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict

from polara.backtester.engine import Backtester
from polara.research_engine.promotion import PromotionError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/strategy", tags=["strategy"])


class StrategyInfo(BaseModel):
    model_config = ConfigDict(strict=True)
    strategy_id: str
    symbol: str
    bar_size: str


class ValidateRequest(BaseModel):
    model_config = ConfigDict(strict=True)
    lookback_bars: int = 500
    bar_size: str = "5 mins"


class BacktestResultResponse(BaseModel):
    model_config = ConfigDict(strict=True)
    strategy_id: str
    run_at: datetime
    bar_size: str
    num_bars: int
    sharpe_ratio: Decimal
    max_drawdown_pct: Decimal
    win_rate_pct: Decimal
    total_return_pct: Decimal
    num_trades: int
    passed: bool
    notes: str | None = None


@router.get("/list", response_model=list[StrategyInfo])
async def list_strategies(request: Request):
    """List all registered strategies."""
    registry = request.app.state.strategy_registry
    return [
        StrategyInfo(strategy_id=s.strategy_id, symbol=s.symbol, bar_size=s.bar_size)
        for s in registry.get_all()
    ]


@router.post("/run/{strategy_id}")
async def run_strategy(strategy_id: str, request: Request):
    """Manually trigger one strategy evaluation cycle.

    Returns 200 + OrderStatus if a signal was generated and an order placed.
    Returns 204 if the strategy ran but generated no signal.
    Returns 404 if the strategy_id is not registered.
    """
    registry = request.app.state.strategy_registry
    market_data_svc = request.app.state.market_data_svc
    order_manager = request.app.state.order_manager

    try:
        strategy = registry.get(strategy_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Strategy '{strategy_id}' not found")

    bars = await market_data_svc.get_bars(
        strategy.symbol, n=strategy.bars_needed, bar_size=strategy.bar_size
    )
    signal = strategy.on_bars(bars)
    if signal is None:
        return Response(status_code=204)

    order_status = await order_manager.process_signal(signal)
    if order_status is None:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=200,
            content={"detail": "Signal generated but rejected by risk guard"},
        )
    return order_status


@router.post("/{strategy_id}/validate", response_model=BacktestResultResponse)
async def validate_strategy(strategy_id: str, body: ValidateRequest, request: Request):
    """Run a backtest on historical bars and record the result.

    Returns BacktestResultResponse. Returns 422 if insufficient bars in store.
    Returns 404 if strategy not registered.
    """
    registry = request.app.state.strategy_registry
    bar_store = request.app.state.bar_store
    backtest_svc = request.app.state.backtest_svc

    try:
        strategy = registry.get(strategy_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Strategy '{strategy_id}' not found")

    backtester = Backtester(strategy=strategy, store=bar_store)
    try:
        result = await asyncio.to_thread(
            backtester.run,
            symbol=strategy.symbol,
            bar_size=body.bar_size,
            lookback_bars=body.lookback_bars,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    await backtest_svc.save(result)
    return BacktestResultResponse(**result.model_dump())


@router.get("/{strategy_id}/backtest-results", response_model=list[BacktestResultResponse])
async def get_backtest_results(
    strategy_id: str,
    request: Request,
    limit: int = Query(10, ge=1, le=100),
):
    """Return past backtest results for a strategy, newest first."""
    registry = request.app.state.strategy_registry
    try:
        registry.get(strategy_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Strategy '{strategy_id}' not found")

    backtest_svc = request.app.state.backtest_svc
    results = await backtest_svc.get_results(strategy_id, limit=limit)
    return [BacktestResultResponse(**r.model_dump()) for r in results]


@router.post("/{strategy_id}/promote")
async def promote_strategy(strategy_id: str, request: Request):
    """Manually promote a strategy from paper/paused to live.

    Requires a passing backtest result on record.
    Returns 409 if promotion conditions are not met.
    Returns 404 if strategy not registered.
    """
    registry = request.app.state.strategy_registry
    try:
        registry.get(strategy_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Strategy '{strategy_id}' not found")

    promotion_gate = request.app.state.promotion_gate
    try:
        await promotion_gate.promote(strategy_id)
    except PromotionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"status": "live"}


@router.post("/{strategy_id}/demote")
async def demote_strategy(strategy_id: str, request: Request):
    """Manually demote a strategy from live to paper.

    Returns 409 if the strategy is not currently live.
    Returns 404 if strategy not registered.
    """
    registry = request.app.state.strategy_registry
    try:
        registry.get(strategy_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Strategy '{strategy_id}' not found")

    promotion_gate = request.app.state.promotion_gate
    try:
        await promotion_gate.demote(strategy_id)
    except PromotionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"status": "paper"}
