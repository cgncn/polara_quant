"""FastAPI application factory and lifespan for Polara Quant."""
import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from decimal import Decimal

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from polara.api.routes.broker import router as broker_router
from polara.api.routes.dashboard import router as dashboard_router
from polara.api.routes.health import router as health_router
from polara.api.routes.market_data import router as market_data_router
from polara.api.routes.strategy import router as strategy_router
from polara.backtester.service import BacktestService
from polara.broker.adapter import BrokerAdapter
from polara.broker.client import IBClient
from polara.calibration.engine import CalibrationEngine
from polara.calibration.scheduler import CalibrationScheduler
from polara.calibration.service import CalibrationService
from polara.dashboard.dashboard_service import DashboardService
from polara.dashboard.trade_service import TradeService
from polara.db.connection import DATABASE_URL, AsyncSessionLocal
from polara.market_data.fetcher import IBFetcher
from polara.market_data.service import MarketDataService
from polara.market_data.store import BarStore
from polara.order_manager.manager import OrderManager
from polara.research_engine.promotion import PromotionGate
from polara.research_engine.registry import StrategyRegistry
from polara.research_engine.scheduler import StrategyScheduler
from polara.research_engine.status_service import StrategyStatusService
from polara.research_engine.strategies.bollinger_bands import BollingerBandStrategy
from polara.research_engine.strategies.ema_bounce import EMABounceStrategy
from polara.research_engine.strategies.gap_fill import GapFillStrategy
from polara.research_engine.strategies.ma_crossover import MACrossoverStrategy
from polara.research_engine.strategies.macd import MACDStrategy
from polara.research_engine.strategies.momentum import MomentumStrategy
from polara.research_engine.strategies.opening_range_breakout import OpeningRangeBreakoutStrategy
from polara.research_engine.strategies.prev_day_breakout import PrevDayBreakoutStrategy
from polara.research_engine.strategies.rsi_mean_reversion import RSIMeanReversionStrategy
from polara.research_engine.strategies.supertrend import SupertrendStrategy
from polara.research_engine.strategies.vwap_mean_reversion import VWAPMeanReversionStrategy
from polara.risk_guard.guard import RiskGuard

logger = logging.getLogger(__name__)

CP_GATEWAY_URL = os.getenv("CP_GATEWAY_URL", "https://cp-gateway:5000/v1/api")


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    masked = _mask_db_url(DATABASE_URL)
    logger.info("Polara Quant %s starting — DB: %s", _get_version(), masked)

    # Only create IBClient + adapter if not already injected (allows test injection)
    if not hasattr(app.state, "broker_adapter"):
        ib_client = IBClient(cp_gateway_url=CP_GATEWAY_URL)
        await ib_client.connect()

        # Dashboard services
        trade_svc = TradeService(db_session_factory=AsyncSessionLocal)
        dashboard_svc = DashboardService(db_session_factory=AsyncSessionLocal)
        app.state.trade_svc = trade_svc
        app.state.dashboard_svc = dashboard_svc

        # Phase 2: Broker adapter
        adapter = BrokerAdapter(
            ib_client=ib_client,
            db_session_factory=AsyncSessionLocal,
            trade_service=trade_svc,
        )
        adapter.start_polling()
        app.state.ib_client = ib_client
        app.state.broker_adapter = adapter

        # Phase 3: Market data
        market_data_db_path = os.environ.get("MARKET_DATA_DB_PATH", "data/market_data.duckdb")
        fetcher = IBFetcher(cp_client=ib_client.cp)
        store = BarStore(db_path=market_data_db_path)
        market_data_svc = MarketDataService(fetcher=fetcher, store=store)
        app.state.market_data_svc = market_data_svc
        app.state.bar_store = store

        # Position sizing — $120 USD per trade (set via POSITION_SIZE_USD env var)
        pos_size_raw = os.environ.get("POSITION_SIZE_USD")
        app.state.position_size_usd = Decimal(pos_size_raw) if pos_size_raw else None

        # Phase 3: Risk guard
        risk_guard = RiskGuard(
            max_position_pct=Decimal(os.environ.get("RISK_MAX_POSITION_PCT", "10")),
            max_daily_loss_pct=Decimal(os.environ.get("RISK_MAX_DAILY_LOSS_PCT", "5")),
        )

        # Phase 4: Strategy status service + backtest service
        status_service = StrategyStatusService(db_session_factory=AsyncSessionLocal)
        app.state.status_service = status_service

        backtest_svc = BacktestService(db_session_factory=AsyncSessionLocal)
        await backtest_svc.migrate()
        app.state.backtest_svc = backtest_svc

        # Phase 3: Order manager (Phase 4: gains status_service check)
        order_manager = OrderManager(
            broker_adapter=adapter,
            risk_guard=risk_guard,
            db_session_factory=AsyncSessionLocal,
            status_service=status_service,
            min_order_quantity=Decimal(os.environ.get("MIN_ORDER_QUANTITY", "1")),
            position_size_usd=Decimal(pos_size_raw) if pos_size_raw else None,
        )
        app.state.order_manager = order_manager

        # Phase 4: Promotion gate
        promotion_gate = PromotionGate(
            status_service=status_service,
            backtest_service=backtest_svc,
        )
        app.state.promotion_gate = promotion_gate

        # Phase 3+4: Strategy registry
        # MA_SYMBOLS / RSI_SYMBOLS are comma-separated ticker lists.
        # One strategy instance is registered per symbol, with IDs like
        # "ma-crossover-pltr", "rsi-mean-reversion-coin", etc.
        ma_symbols = _parse_symbols("MA_SYMBOLS", "AAPL")
        rsi_symbols = _parse_symbols("RSI_SYMBOLS", "AAPL")
        macd_symbols = _parse_symbols("MACD_SYMBOLS", "")
        bb_symbols = _parse_symbols("BB_SYMBOLS", "")
        bb_d30_symbols = _parse_symbols("BB_D30_SYMBOLS", "")
        bb_d15_symbols = _parse_symbols("BB_D15_SYMBOLS", "")
        mom_symbols = _parse_symbols("MOM_SYMBOLS", "")

        ma_stop = _decimal_env("MA_STOP_LOSS_PCT")
        ma_tp = _decimal_env("MA_TAKE_PROFIT_PCT")
        rsi_stop = _decimal_env("RSI_STOP_LOSS_PCT")
        rsi_tp = _decimal_env("RSI_TAKE_PROFIT_PCT")
        macd_stop = _decimal_env("MACD_STOP_LOSS_PCT")
        macd_tp = _decimal_env("MACD_TAKE_PROFIT_PCT")
        bb_stop = _decimal_env("BB_STOP_LOSS_PCT")
        bb_tp = _decimal_env("BB_TAKE_PROFIT_PCT")
        bb_d30_stop = _decimal_env("BB_D30_STOP_LOSS_PCT")
        bb_d30_tp = _decimal_env("BB_D30_TAKE_PROFIT_PCT")
        bb_d15_stop = _decimal_env("BB_D15_STOP_LOSS_PCT")
        bb_d15_tp = _decimal_env("BB_D15_TAKE_PROFIT_PCT")
        mom_stop = _decimal_env("MOM_STOP_LOSS_PCT")
        mom_tp = _decimal_env("MOM_TAKE_PROFIT_PCT")

        registry = StrategyRegistry()

        for symbol in ma_symbols:
            registry.register(
                MACrossoverStrategy(
                    strategy_id=f"ma-crossover-{symbol.lower()}",
                    symbol=symbol,
                    fast_period=int(os.environ.get("MA_FAST_PERIOD", "5")),
                    slow_period=int(os.environ.get("MA_SLOW_PERIOD", "20")),
                    quantity=Decimal(os.environ.get("MA_QUANTITY", "1")),
                    bar_size=os.environ.get("MA_BAR_SIZE", "1 hour"),
                    stop_loss_pct=ma_stop,
                    take_profit_pct=ma_tp,
                )
            )

        for symbol in rsi_symbols:
            registry.register(
                RSIMeanReversionStrategy(
                    strategy_id=f"rsi-mean-reversion-{symbol.lower()}",
                    symbol=symbol,
                    period=int(os.environ.get("RSI_PERIOD", "14")),
                    oversold=Decimal(os.environ.get("RSI_OVERSOLD", "30")),
                    overbought=Decimal(os.environ.get("RSI_OVERBOUGHT", "70")),
                    quantity=Decimal(os.environ.get("RSI_QUANTITY", "1")),
                    bar_size=os.environ.get("RSI_BAR_SIZE", "1 hour"),
                    stop_loss_pct=rsi_stop,
                    take_profit_pct=rsi_tp,
                )
            )

        for symbol in macd_symbols:
            registry.register(
                MACDStrategy(
                    strategy_id=f"macd-{symbol.lower()}",
                    symbol=symbol,
                    fast_period=int(os.environ.get("MACD_FAST", "12")),
                    slow_period=int(os.environ.get("MACD_SLOW", "26")),
                    signal_period=int(os.environ.get("MACD_SIGNAL", "9")),
                    quantity=Decimal(os.environ.get("MACD_QUANTITY", "1")),
                    bar_size=os.environ.get("MACD_BAR_SIZE", "1 hour"),
                    stop_loss_pct=macd_stop,
                    take_profit_pct=macd_tp,
                )
            )

        for symbol in bb_symbols:
            registry.register(
                BollingerBandStrategy(
                    strategy_id=f"bb-{symbol.lower()}",
                    symbol=symbol,
                    period=int(os.environ.get("BB_PERIOD", "20")),
                    num_std=Decimal(os.environ.get("BB_NUM_STD", "2")),
                    quantity=Decimal(os.environ.get("BB_QUANTITY", "1")),
                    bar_size=os.environ.get("BB_BAR_SIZE", "1 hour"),
                    stop_loss_pct=bb_stop,
                    take_profit_pct=bb_tp,
                )
            )

        for symbol in bb_d30_symbols:
            registry.register(
                BollingerBandStrategy(
                    strategy_id=f"bb-{symbol.lower()}",
                    symbol=symbol,
                    period=int(os.environ.get("BB_D30_PERIOD", "30")),
                    num_std=Decimal(os.environ.get("BB_D30_NUM_STD", "2.0")),
                    quantity=Decimal(os.environ.get("BB_D30_QUANTITY", "1")),
                    bar_size=os.environ.get("BB_D30_BAR_SIZE", "1 day"),
                    stop_loss_pct=bb_d30_stop,
                    take_profit_pct=bb_d30_tp,
                )
            )

        for symbol in bb_d15_symbols:
            registry.register(
                BollingerBandStrategy(
                    strategy_id=f"bb-{symbol.lower()}",
                    symbol=symbol,
                    period=int(os.environ.get("BB_D15_PERIOD", "15")),
                    num_std=Decimal(os.environ.get("BB_D15_NUM_STD", "2.0")),
                    quantity=Decimal(os.environ.get("BB_D15_QUANTITY", "1")),
                    bar_size=os.environ.get("BB_D15_BAR_SIZE", "1 day"),
                    stop_loss_pct=bb_d15_stop,
                    take_profit_pct=bb_d15_tp,
                )
            )

        for symbol in mom_symbols:
            registry.register(
                MomentumStrategy(
                    strategy_id=f"momentum-{symbol.lower()}",
                    symbol=symbol,
                    period=int(os.environ.get("MOM_PERIOD", "14")),
                    threshold=Decimal(os.environ.get("MOM_THRESHOLD", "2")),
                    quantity=Decimal(os.environ.get("MOM_QUANTITY", "1")),
                    bar_size=os.environ.get("MOM_BAR_SIZE", "1 hour"),
                    stop_loss_pct=mom_stop,
                    take_profit_pct=mom_tp,
                )
            )

        # ── Intraday strategies (30-min bars, paper by default) ──────────────
        intraday_bar = os.environ.get("INTRADAY_BAR_SIZE", "30 mins")

        vwap_symbols   = _parse_symbols("VWAP_SYMBOLS",     "MSTR,SMCI")
        orb_symbols    = _parse_symbols("ORB_SYMBOLS",      "COIN,PLTR,MSTR,RNR")
        gap_symbols    = _parse_symbols("GAP_FILL_SYMBOLS", "MSTR,COIN,PLTR,RNR")
        pdhl_symbols   = _parse_symbols("PDHL_SYMBOLS",     "MSTR,COIN,PLTR")

        for symbol in vwap_symbols:
            registry.register(VWAPMeanReversionStrategy(
                strategy_id=f"vwap-{symbol.lower()}",
                symbol=symbol,
                bar_size=intraday_bar,
            ))

        for symbol in orb_symbols:
            registry.register(OpeningRangeBreakoutStrategy(
                strategy_id=f"orb-{symbol.lower()}",
                symbol=symbol,
                bar_size=intraday_bar,
            ))

        for symbol in gap_symbols:
            registry.register(GapFillStrategy(
                strategy_id=f"gap-{symbol.lower()}",
                symbol=symbol,
                bar_size=intraday_bar,
            ))

        for symbol in pdhl_symbols:
            registry.register(PrevDayBreakoutStrategy(
                strategy_id=f"pdhl-{symbol.lower()}",
                symbol=symbol,
                bar_size=intraday_bar,
            ))

        supertrend_symbols = _parse_symbols("SUPERTREND_SYMBOLS", "COIN,PLTR,MSTR,SMCI")
        for symbol in supertrend_symbols:
            registry.register(SupertrendStrategy(
                strategy_id=f"supertrend-{symbol.lower()}",
                symbol=symbol,
                bar_size=intraday_bar,
            ))

        ema_bounce_symbols = _parse_symbols("EMA_BOUNCE_SYMBOLS", "COIN,PLTR,MSTR,RNR")
        for symbol in ema_bounce_symbols:
            registry.register(EMABounceStrategy(
                strategy_id=f"ema-bounce-{symbol.lower()}",
                symbol=symbol,
                bar_size=intraday_bar,
            ))

        app.state.strategy_registry = registry

        # Seed DB status rows for all registered strategies (paper by default)
        for strategy in registry.get_all():
            await status_service.ensure_registered(
                strategy_id=strategy.strategy_id,
                name=strategy.strategy_id,
                status="paper",
            )

        # ── Calibration engine + daily scheduler ─────────────────────────────
        cal_pos_size_raw = os.environ.get("INTRADAY_POSITION_SIZE_USD", "5000")
        calibration_svc = CalibrationService(db_session_factory=AsyncSessionLocal)
        await calibration_svc.migrate()
        app.state.calibration_svc = calibration_svc

        calibration_engine = CalibrationEngine(
            registry=registry,
            store=store,
            lookback_bars=int(os.environ.get("CALIBRATION_LOOKBACK_BARS", "780")),
            position_size_usd=Decimal(cal_pos_size_raw),
        )
        app.state.calibration_engine = calibration_engine

        calibration_scheduler = CalibrationScheduler(
            engine=calibration_engine,
            service=calibration_svc,
            interval_hours=int(os.environ.get("CALIBRATION_INTERVAL_HOURS", "24")),
        )

        # Background tasks
        scheduler = StrategyScheduler(
            market_data_svc=market_data_svc,
            registry=registry,
            order_manager=order_manager,
            interval_seconds=int(os.environ.get("STRATEGY_INTERVAL_SECONDS", "60")),
        )
        pnl_task = asyncio.create_task(adapter.pnl_snapshot_loop())
        scheduler_task = asyncio.create_task(scheduler.run())
        calibration_task = asyncio.create_task(calibration_scheduler.run())
        app.state.pnl_task = pnl_task
        app.state.scheduler_task = scheduler_task
        app.state.calibration_task = calibration_task

        logger.info(
            "Trading loop started — %d strategies registered (%s interval) — "
            "calibration every %sh",
            len(registry.get_all()),
            os.environ.get("STRATEGY_INTERVAL_SECONDS", "60") + "s",
            os.environ.get("CALIBRATION_INTERVAL_HOURS", "24"),
        )

    yield

    # Shutdown
    for attr in ("scheduler_task", "pnl_task", "calibration_task"):
        if hasattr(app.state, attr):
            getattr(app.state, attr).cancel()
    tasks_to_gather = []
    if hasattr(app.state, "scheduler_task"):
        tasks_to_gather.append(app.state.scheduler_task)
    if hasattr(app.state, "pnl_task"):
        tasks_to_gather.append(app.state.pnl_task)
    if hasattr(app.state, "calibration_task"):
        tasks_to_gather.append(app.state.calibration_task)
    if tasks_to_gather:
        try:
            await asyncio.gather(*tasks_to_gather, return_exceptions=True)
        except Exception:
            pass
    if hasattr(app.state, "ib_client"):
        await app.state.ib_client.disconnect()
    logger.info("Polara Quant %s stopped", _get_version())


def _decimal_env(key: str) -> Decimal | None:
    """Return Decimal(env[key]) or None if the key is unset/empty."""
    val = os.environ.get(key)
    return Decimal(val) if val else None


def _parse_symbols(env_var: str, default: str) -> list[str]:
    """Return an uppercase, deduplicated symbol list from a comma-separated env var.

    Example: MA_SYMBOLS=pltr,COIN, smci  →  ["PLTR", "COIN", "SMCI"]
    """
    raw = os.environ.get(env_var, default)
    seen: set[str] = set()
    result: list[str] = []
    for tok in raw.split(","):
        sym = tok.strip().upper()
        if sym and sym not in seen:
            seen.add(sym)
            result.append(sym)
    return result


def create_app() -> FastAPI:
    from pathlib import Path

    app = FastAPI(title="Polara Quant", version=_get_version(), lifespan=_lifespan)

    app.include_router(health_router)
    app.include_router(broker_router)
    app.include_router(market_data_router)
    app.include_router(strategy_router)
    app.include_router(dashboard_router)

    static_dir = Path(__file__).parent.parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

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
