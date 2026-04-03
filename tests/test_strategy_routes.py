"""Tests for GET /strategy/list and POST /strategy/run/{strategy_id} and Phase 4 endpoints."""
from datetime import datetime, UTC
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
import pytest
from httpx import AsyncClient, ASGITransport

from polara.api.main import create_app
from polara.backtester.schemas import BacktestResult
from polara.backtester.service import BacktestService
from polara.broker.schemas import OrderStatus
from polara.order_manager.manager import OrderManager
from polara.research_engine.promotion import PromotionError, PromotionGate
from polara.research_engine.registry import StrategyRegistry
from polara.schemas.signals import Signal


def make_signal() -> Signal:
    return Signal(
        signal_id=uuid4(),
        strategy_id="ma-crossover-aapl",
        symbol="AAPL",
        strength=Decimal("1"),
        generated_at=datetime.now(UTC),
    )


def make_order_status() -> OrderStatus:
    return OrderStatus(
        order_id=uuid4(),
        ib_order_id=None,
        status="submitted",
        submitted_at=datetime.now(UTC),
        filled_at=None,
    )


def make_backtest_result(passed: bool = True) -> BacktestResult:
    return BacktestResult(
        strategy_id="ma-crossover-aapl",
        run_at=datetime.now(UTC),
        bar_size="5 mins",
        num_bars=200,
        sharpe_ratio=Decimal("1.2"),
        max_drawdown_pct=Decimal("5.0"),
        win_rate_pct=Decimal("60.0"),
        total_return_pct=Decimal("12.0"),
        num_trades=10,
        passed=passed,
    )


def make_mock_bar_store(num_bars: int = 200):
    store = MagicMock()
    store.query = MagicMock(return_value=[MagicMock()] * num_bars)
    return store


@pytest.fixture
def app():
    application = create_app()

    mock_registry = MagicMock(spec=StrategyRegistry)
    mock_strategy = MagicMock()
    mock_strategy.strategy_id = "ma-crossover-aapl"
    mock_strategy.symbol = "AAPL"
    mock_strategy.bars_needed = 51
    mock_strategy.bar_size = "5 mins"
    mock_strategy.on_bars = MagicMock(return_value=make_signal())
    mock_registry.get_all = MagicMock(return_value=[mock_strategy])
    mock_registry.get = MagicMock(return_value=mock_strategy)

    mock_manager = AsyncMock(spec=OrderManager)
    mock_manager.process_signal = AsyncMock(return_value=make_order_status())

    mock_market_data = AsyncMock()
    mock_market_data.get_bars = AsyncMock(return_value=[])

    mock_backtest_svc = AsyncMock(spec=BacktestService)
    mock_backtest_svc.save = AsyncMock()
    mock_backtest_svc.get_results = AsyncMock(return_value=[make_backtest_result()])

    mock_promotion_gate = AsyncMock(spec=PromotionGate)
    mock_promotion_gate.promote = AsyncMock()
    mock_promotion_gate.demote = AsyncMock()

    application.state.strategy_registry = mock_registry
    application.state.order_manager = mock_manager
    application.state.market_data_svc = mock_market_data
    application.state.backtest_svc = mock_backtest_svc
    application.state.promotion_gate = mock_promotion_gate
    application.state.bar_store = make_mock_bar_store()
    return application


@pytest.mark.asyncio
async def test_post_strategy_run_returns_200(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/strategy/run/ma-crossover-aapl")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_post_strategy_run_unknown_returns_404(app):
    app.state.strategy_registry.get = MagicMock(side_effect=KeyError("unknown"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/strategy/run/unknown-strategy")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_post_strategy_run_no_signal_returns_204(app):
    app.state.strategy_registry.get = MagicMock(
        return_value=MagicMock(
            strategy_id="ma-crossover-aapl",
            symbol="AAPL",
            bars_needed=51,
            bar_size="5 mins",
            on_bars=MagicMock(return_value=None),
        )
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/strategy/run/ma-crossover-aapl")
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_get_strategy_list_returns_registered_strategies(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/strategy/list")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["strategy_id"] == "ma-crossover-aapl"


# --- Phase 4: /validate endpoint ---

@pytest.mark.asyncio
async def test_post_validate_returns_200_with_result(app):
    """POST /strategy/{id}/validate runs backtest and returns BacktestResultResponse."""
    # Patch Backtester.run via asyncio.to_thread — mock the bar_store to control bars
    result = make_backtest_result(passed=True)
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "polara.api.routes.strategy.Backtester.run",
            lambda self, **kwargs: result,
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/strategy/ma-crossover-aapl/validate",
                json={"lookback_bars": 200, "bar_size": "5 mins"},
            )
    assert response.status_code == 200
    data = response.json()
    assert data["strategy_id"] == "ma-crossover-aapl"
    assert "sharpe_ratio" in data
    assert "passed" in data


@pytest.mark.asyncio
async def test_post_validate_unknown_strategy_returns_404(app):
    app.state.strategy_registry.get = MagicMock(side_effect=KeyError("unknown"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/strategy/unknown-id/validate",
            json={"lookback_bars": 200, "bar_size": "5 mins"},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_post_validate_insufficient_bars_returns_422(app):
    """When Backtester.run raises ValueError (insufficient bars), return 422."""
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "polara.api.routes.strategy.Backtester.run",
            lambda self, **kwargs: (_ for _ in ()).throw(ValueError("Insufficient bars")),
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/strategy/ma-crossover-aapl/validate",
                json={"lookback_bars": 5, "bar_size": "5 mins"},
            )
    assert response.status_code == 422


# --- Phase 4: /backtest-results endpoint ---

@pytest.mark.asyncio
async def test_get_backtest_results_returns_list(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/strategy/ma-crossover-aapl/backtest-results")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["strategy_id"] == "ma-crossover-aapl"


@pytest.mark.asyncio
async def test_get_backtest_results_unknown_strategy_404(app):
    app.state.strategy_registry.get = MagicMock(side_effect=KeyError("unknown"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/strategy/unknown-id/backtest-results")
    assert response.status_code == 404


# --- Phase 4: /promote endpoint ---

@pytest.mark.asyncio
async def test_post_promote_returns_200_and_live_status(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/strategy/ma-crossover-aapl/promote")
    assert response.status_code == 200
    assert response.json()["status"] == "live"
    app.state.promotion_gate.promote.assert_called_once_with("ma-crossover-aapl")


@pytest.mark.asyncio
async def test_post_promote_returns_409_on_promotion_error(app):
    app.state.promotion_gate.promote = AsyncMock(
        side_effect=PromotionError("no passing backtest")
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/strategy/ma-crossover-aapl/promote")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_post_promote_unknown_strategy_404(app):
    app.state.strategy_registry.get = MagicMock(side_effect=KeyError("unknown"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/strategy/unknown-id/promote")
    assert response.status_code == 404


# --- Phase 4: /demote endpoint ---

@pytest.mark.asyncio
async def test_post_demote_returns_200_and_paper_status(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/strategy/ma-crossover-aapl/demote")
    assert response.status_code == 200
    assert response.json()["status"] == "paper"
    app.state.promotion_gate.demote.assert_called_once_with("ma-crossover-aapl")


@pytest.mark.asyncio
async def test_post_demote_returns_409_on_promotion_error(app):
    app.state.promotion_gate.demote = AsyncMock(
        side_effect=PromotionError("not live")
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/strategy/ma-crossover-aapl/demote")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_post_demote_unknown_strategy_404(app):
    app.state.strategy_registry.get = MagicMock(side_effect=KeyError("unknown"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/strategy/unknown-id/demote")
    assert response.status_code == 404
