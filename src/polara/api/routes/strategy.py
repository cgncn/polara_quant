"""Strategy REST endpoints — manual trigger and strategy listing."""
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/strategy", tags=["strategy"])


class StrategyInfo(BaseModel):
    model_config = ConfigDict(strict=True)
    strategy_id: str
    symbol: str
    bar_size: str


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
