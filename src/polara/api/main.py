import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from polara.api.routes.broker import router as broker_router
from polara.api.routes.health import router as health_router
from polara.broker.adapter import BrokerAdapter
from polara.broker.client import IBClient
from polara.db.connection import DATABASE_URL, AsyncSessionLocal

logger = logging.getLogger(__name__)

IB_HOST = os.getenv("IB_HOST", "ib-gateway")
IB_PORT = int(os.getenv("IB_PORT", "4003"))
IB_CLIENT_ID = int(os.getenv("IB_CLIENT_ID", "1"))


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    masked = _mask_db_url(DATABASE_URL)
    logger.info("Polara Quant %s starting — DB: %s", _get_version(), masked)

    # Only create IBClient + adapter if not already injected (allows test injection)
    if not hasattr(app.state, "broker_adapter"):
        ib_client = IBClient(host=IB_HOST, port=IB_PORT, client_id=IB_CLIENT_ID)
        await ib_client.connect()
        app.state.ib_client = ib_client

        # Build adapter and register fill/order-status callbacks
        adapter = BrokerAdapter(ib_client=ib_client, db_session_factory=AsyncSessionLocal)
        adapter._register_callbacks()
        app.state.broker_adapter = adapter

        # Start P&L snapshot background task (every 60 seconds)
        pnl_task = asyncio.create_task(adapter.pnl_snapshot_loop())
        app.state.pnl_task = pnl_task

    yield

    # Shutdown
    if hasattr(app.state, "pnl_task"):
        app.state.pnl_task.cancel()
        try:
            await app.state.pnl_task
        except asyncio.CancelledError:
            pass
    if hasattr(app.state, "ib_client"):
        await app.state.ib_client.disconnect()
    logger.info("Polara Quant %s stopped", _get_version())


def create_app() -> FastAPI:
    app = FastAPI(title="Polara Quant", version=_get_version(), lifespan=_lifespan)

    app.include_router(health_router)
    app.include_router(broker_router)

    return app


def _mask_db_url(url: str) -> str:
    """Mask credentials in DB URL for safe logging."""
    if "@" in url:
        scheme, rest = url.split("://", 1)
        host_part = rest.split("@", 1)[1]
        return f"{scheme}://***@{host_part}"
    return url


def _get_version() -> str:
    from polara import __version__

    return __version__


# Module-level app instance for uvicorn
app = create_app()
