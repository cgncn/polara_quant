"""FastAPI application factory and lifespan for Polara Quant."""
import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from decimal import Decimal

from fastapi import FastAPI

from polara.api.routes.broker import router as broker_router
from polara.api.routes.health import router as health_router
from polara.api.routes.market_data import router as market_data_router
from polara.api.routes.strategy import router as strategy_router
from polara.broker.adapter import BrokerAdapter
from polara.broker.client import IBClient
from polara.db.connection import DATABASE_URL, AsyncSessionLocal
from polara.market_data.fetcher import IBFetcher
from polara.market_data.service import MarketDataService
from polara.market_data.store import BarStore
from polara.order_manager.manager import OrderManager
from polara.research_engine.registry import StrategyRegistry
from polara.research_engine.scheduler import StrategyScheduler
from polara.research_engine.strategies.ma_crossover import MACrossoverStrategy
from polara.risk_guard.guard import RiskGuard

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
        try:
            await ib_client.connect()
        except Exception:
            logger.error("Failed to connect to IB Gateway on startup", exc_info=True)
            await ib_client.disconnect()
            raise

        # Phase 2: Broker adapter
        adapter = BrokerAdapter(ib_client=ib_client, db_session_factory=AsyncSessionLocal)
        adapter._register_callbacks()
        app.state.ib_client = ib_client
        app.state.broker_adapter = adapter

        # Phase 3: Market data
        market_data_db_path = os.environ.get("MARKET_DATA_DB_PATH", "data/market_data.duckdb")
        fetcher = IBFetcher(ib=ib_client.ib)
        store = BarStore(db_path=market_data_db_path)
        market_data_svc = MarketDataService(fetcher=fetcher, store=store)
        app.state.market_data_svc = market_data_svc

        # Phase 3: Risk guard
        risk_guard = RiskGuard(
            max_position_pct=Decimal(os.environ.get("RISK_MAX_POSITION_PCT", "10")),
            max_daily_loss_pct=Decimal(os.environ.get("RISK_MAX_DAILY_LOSS_PCT", "5")),
        )

        # Phase 3: Order manager
        order_manager = OrderManager(
            broker_adapter=adapter,
            risk_guard=risk_guard,
            db_session_factory=AsyncSessionLocal,
        )
        app.state.order_manager = order_manager

        # Phase 3: Strategy registry
        registry = StrategyRegistry()
        registry.register(
            MACrossoverStrategy(
                strategy_id=os.environ.get("MA_STRATEGY_ID", "ma-crossover-aapl"),
                symbol=os.environ.get("MA_STRATEGY_SYMBOL", "AAPL"),
                fast_period=int(os.environ.get("MA_FAST_PERIOD", "10")),
                slow_period=int(os.environ.get("MA_SLOW_PERIOD", "50")),
                quantity=Decimal(os.environ.get("MA_QUANTITY", "1")),
                bar_size=os.environ.get("MA_BAR_SIZE", "5 mins"),
            )
        )
        app.state.strategy_registry = registry

        # Background tasks
        scheduler = StrategyScheduler(
            market_data_svc=market_data_svc,
            registry=registry,
            order_manager=order_manager,
            interval_seconds=int(os.environ.get("STRATEGY_INTERVAL_SECONDS", "60")),
        )
        pnl_task = asyncio.create_task(adapter.pnl_snapshot_loop())
        scheduler_task = asyncio.create_task(scheduler.run())
        app.state.pnl_task = pnl_task
        app.state.scheduler_task = scheduler_task

        logger.info(
            "Phase 3 trading loop started — strategy scheduler running every %ss",
            os.environ.get("STRATEGY_INTERVAL_SECONDS", "60"),
        )

    yield

    # Shutdown
    if hasattr(app.state, "scheduler_task"):
        app.state.scheduler_task.cancel()
    if hasattr(app.state, "pnl_task"):
        app.state.pnl_task.cancel()
    tasks_to_gather = []
    if hasattr(app.state, "scheduler_task"):
        tasks_to_gather.append(app.state.scheduler_task)
    if hasattr(app.state, "pnl_task"):
        tasks_to_gather.append(app.state.pnl_task)
    if tasks_to_gather:
        try:
            await asyncio.gather(*tasks_to_gather, return_exceptions=True)
        except Exception:
            pass
    if hasattr(app.state, "ib_client"):
        await app.state.ib_client.disconnect()
    logger.info("Polara Quant %s stopped", _get_version())


def create_app() -> FastAPI:
    app = FastAPI(title="Polara Quant", version=_get_version(), lifespan=_lifespan)

    app.include_router(health_router)
    app.include_router(broker_router)
    app.include_router(market_data_router)
    app.include_router(strategy_router)

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
