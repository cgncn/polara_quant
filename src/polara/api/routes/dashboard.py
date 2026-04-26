"""Dashboard API routes — JSON endpoints consumed by the frontend."""
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from polara.dashboard.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _svc(request: Request) -> DashboardService:
    return request.app.state.dashboard_svc  # type: ignore[no-any-return]


# ── JSON data endpoints ────────────────────────────────────────────────────────

@router.get("/api/summary/today")
async def today_summary(request: Request):
    return await _svc(request).today_summary()


@router.get("/api/pnl/history")
async def pnl_history(request: Request, days: int = Query(30, ge=1, le=365)):
    return await _svc(request).pnl_history(days=days)


@router.get("/api/trades")
async def trades(
    request: Request,
    date: str | None = Query(None),
    strategy: str | None = Query(None),
    symbol: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
):
    return await _svc(request).trades_filtered(
        date=date, strategy_id=strategy, symbol=symbol, limit=limit
    )


@router.get("/api/strategy/performance")
async def strategy_performance(request: Request):
    return await _svc(request).strategy_performance()


@router.get("/api/symbol/performance")
async def symbol_performance(request: Request):
    return await _svc(request).symbol_performance()


@router.get("/api/status")
async def broker_status(request: Request):
    adapter = request.app.state.broker_adapter
    status = await adapter.get_broker_status()
    account = None
    try:
        account = await adapter.get_account()
    except Exception:
        pass
    return {
        "connected": status.connected,
        "authenticated": status.connected,
        "account_id": status.account_id,
        "nav": str(account.net_liquidation) if account else None,
        "currency": account.currency if account else None,
        "timestamp": status.ib_server_time.isoformat() if status.ib_server_time else None,
    }


# ── HTML page routes ───────────────────────────────────────────────────────────

def _html(path: str) -> HTMLResponse:
    from pathlib import Path
    static_dir = Path(__file__).parent.parent / "static" / "dashboard"
    content = (static_dir / path).read_text()
    return HTMLResponse(content)


@router.get("/", response_class=HTMLResponse)
async def page_today():
    return _html("today.html")


@router.get("/calendar", response_class=HTMLResponse)
async def page_calendar():
    return _html("calendar.html")


@router.get("/strategies", response_class=HTMLResponse)
async def page_strategies():
    return _html("strategies.html")


@router.get("/positions", response_class=HTMLResponse)
async def page_positions():
    return _html("positions.html")
