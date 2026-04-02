"""Broker API routes — all IB Gateway interactions proxied through BrokerAdapter."""
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from polara.broker.adapter import BrokerAdapter, BrokerDisconnectedError
from polara.broker.schemas import (
    AccountInfo,
    BrokerStatus,
    OrderStatus,
    OrderWithFills,
    PnLSnapshot,
    Position,
)
from polara.db.connection import get_db
from polara.schemas.orders import OrderRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/broker", tags=["broker"])


def _get_adapter(request: Request) -> BrokerAdapter:
    """FastAPI dependency — retrieves the BrokerAdapter from app.state."""
    return request.app.state.broker_adapter  # type: ignore[no-any-return]


def _disconnected(exc: BrokerDisconnectedError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=str(exc),
    )


# ── GET /broker/status ────────────────────────────────────────────────────────

@router.get("/status", response_model=BrokerStatus)
async def get_broker_status(
    adapter: BrokerAdapter = Depends(_get_adapter),
) -> BrokerStatus:
    return await adapter.get_broker_status()


# ── GET /broker/account ───────────────────────────────────────────────────────

@router.get("/account", response_model=AccountInfo)
async def get_account(
    adapter: BrokerAdapter = Depends(_get_adapter),
) -> AccountInfo:
    try:
        return await adapter.get_account()
    except BrokerDisconnectedError as exc:
        raise _disconnected(exc) from exc


# ── GET /broker/positions ─────────────────────────────────────────────────────

@router.get("/positions", response_model=list[Position])
async def get_positions(
    adapter: BrokerAdapter = Depends(_get_adapter),
) -> list[Position]:
    try:
        return await adapter.get_positions()
    except BrokerDisconnectedError as exc:
        raise _disconnected(exc) from exc


# ── POST /broker/orders ───────────────────────────────────────────────────────

@router.post("/orders", status_code=status.HTTP_201_CREATED)
async def place_order(
    request: Request,
    adapter: BrokerAdapter = Depends(_get_adapter),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Accept an OrderRequest JSON body and submit it via the broker adapter.

    Uses model_validate_json so that Pydantic's JSON coercion rules apply even
    when the model is configured with strict=True (e.g. str -> Decimal).
    """
    body = await request.body()
    try:
        req = OrderRequest.model_validate_json(body)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    try:
        await adapter.place_order(req, db=db)
    except BrokerDisconnectedError as exc:
        raise _disconnected(exc) from exc
    result = OrderStatus(
        order_id=req.order_id,
        ib_order_id=None,
        status="submitted",
        submitted_at=datetime.now(UTC),
        filled_at=None,
    )
    return JSONResponse(
        content=result.model_dump(mode="json"),
        status_code=status.HTTP_201_CREATED,
    )


# ── GET /broker/orders ────────────────────────────────────────────────────────

@router.get("/orders", response_model=list[OrderStatus])
async def list_orders(
    adapter: BrokerAdapter = Depends(_get_adapter),
    db: AsyncSession = Depends(get_db),
) -> list[OrderStatus]:
    return await adapter.list_orders(db=db)


# ── GET /broker/orders/{order_id} ─────────────────────────────────────────────

@router.get("/orders/{order_id}", response_model=OrderWithFills)
async def get_order(
    order_id: str,
    adapter: BrokerAdapter = Depends(_get_adapter),
    db: AsyncSession = Depends(get_db),
) -> OrderWithFills:
    result = await adapter.get_order_with_fills(order_id=order_id, db=db)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return result


# ── DELETE /broker/orders/{order_id} ─────────────────────────────────────────

@router.delete("/orders/{order_id}", response_model=OrderStatus)
async def cancel_order(
    order_id: str,
    adapter: BrokerAdapter = Depends(_get_adapter),
    db: AsyncSession = Depends(get_db),
) -> OrderStatus:
    try:
        return await adapter.cancel_order(order_id=order_id, db=db)
    except BrokerDisconnectedError as exc:
        raise _disconnected(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


# ── GET /broker/pnl/history ───────────────────────────────────────────────────

@router.get("/pnl/history", response_model=list[PnLSnapshot])
async def pnl_history(
    adapter: BrokerAdapter = Depends(_get_adapter),
    db: AsyncSession = Depends(get_db),
) -> list[PnLSnapshot]:
    return await adapter.list_pnl_history(db=db)
