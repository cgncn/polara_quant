"""Market data REST endpoints."""
import logging

from fastapi import APIRouter, HTTPException, Request

from polara.schemas.market import Bar, Quote

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/market-data", tags=["market-data"])


def _get_market_data_svc(request: Request):
    return request.app.state.market_data_svc


@router.get("/bars/{symbol}", response_model=list[Bar])
async def get_bars(symbol: str, request: Request, n: int = 100, bar_size: str = "5 mins"):
    """Return the n most recent bars for symbol (oldest-first)."""
    svc = _get_market_data_svc(request)
    try:
        return await svc.get_bars(symbol.upper(), n=n, bar_size=bar_size)
    except Exception:
        logger.error("Failed to get bars for %s", symbol, exc_info=True)
        raise HTTPException(status_code=503, detail="Market data service unavailable")


@router.get("/quote/{symbol}", response_model=Quote)
async def get_quote(symbol: str, request: Request):
    """Return the live bid/ask quote for symbol."""
    svc = _get_market_data_svc(request)
    try:
        return await svc.get_latest_quote(symbol.upper())
    except Exception:
        logger.error("Failed to get quote for %s", symbol, exc_info=True)
        raise HTTPException(status_code=503, detail="Market data service unavailable")
