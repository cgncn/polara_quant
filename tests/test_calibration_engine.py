"""Tests for CalibrationEngine."""
import dataclasses
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from polara.backtester.schemas import BacktestResult
from polara.calibration.engine import CalibrationEngine
from polara.calibration.schemas import CalibrationResult
from polara.research_engine.base import Strategy
from polara.research_engine.registry import StrategyRegistry
from polara.schemas.market import Bar
from polara.schemas.signals import Signal


# ---------------------------------------------------------------------------
# Minimal concrete strategy for testing
# ---------------------------------------------------------------------------

@dataclass
class _MockStrategy(Strategy):
    strategy_id: str = "mock_strat"
    symbol: str = "AAPL"
    bars_needed: int = 2
    bar_size: str = "5 mins"
    threshold: Decimal = Decimal("0.001")

    def on_bars(self, bars: list[Bar]) -> Signal | None:
        return None


@dataclass
class _MockStrategyWithGrid(_MockStrategy):
    PARAM_GRID: dict = dataclasses.field(
        default_factory=lambda: {"threshold": ["0.001", "0.002", "0.003"]},
        init=False,
        repr=False,
        compare=False,
    )


def _make_backtest_result(sharpe: str = "1.2") -> BacktestResult:
    return BacktestResult(
        strategy_id="mock_strat",
        run_at=datetime.now(UTC),
        bar_size="5 mins",
        num_bars=100,
        sharpe_ratio=Decimal(sharpe),
        max_drawdown_pct=Decimal("5"),
        win_rate_pct=Decimal("60"),
        total_return_pct=Decimal("10"),
        num_trades=10,
        passed=True,
        notes=None,
    )


# ---------------------------------------------------------------------------
# _size_multiplier tests
# ---------------------------------------------------------------------------

def _make_engine() -> CalibrationEngine:
    registry = StrategyRegistry()
    store = MagicMock()
    return CalibrationEngine(registry=registry, store=store)


def test_size_multiplier_high_sharpe():
    engine = _make_engine()
    assert engine._size_multiplier(Decimal("1.6")) == Decimal("2.0")


def test_size_multiplier_mid_high_sharpe():
    engine = _make_engine()
    assert engine._size_multiplier(Decimal("1.2")) == Decimal("1.5")


def test_size_multiplier_passing_sharpe():
    engine = _make_engine()
    assert engine._size_multiplier(Decimal("0.7")) == Decimal("1.0")


def test_size_multiplier_below_threshold():
    engine = _make_engine()
    assert engine._size_multiplier(Decimal("0.3")) == Decimal("0.5")


def test_size_multiplier_boundary_1_5():
    engine = _make_engine()
    assert engine._size_multiplier(Decimal("1.5")) == Decimal("2.0")


def test_size_multiplier_boundary_1_0():
    engine = _make_engine()
    assert engine._size_multiplier(Decimal("1.0")) == Decimal("1.5")


def test_size_multiplier_boundary_0_5():
    engine = _make_engine()
    assert engine._size_multiplier(Decimal("0.5")) == Decimal("1.0")


# ---------------------------------------------------------------------------
# calibrate_one tests
# ---------------------------------------------------------------------------

def test_calibrate_one_applies_size_multiplier():
    registry = StrategyRegistry()
    strategy = _MockStrategy()
    registry.register(strategy)
    store = MagicMock()
    engine = CalibrationEngine(registry=registry, store=store)

    mock_result = _make_backtest_result(sharpe="1.6")
    with patch.object(engine, "_run_backtest", return_value=mock_result):
        result = engine.calibrate_one("mock_strat", "AAPL")

    assert result is not None
    assert result.size_multiplier == Decimal("2.0")
    assert strategy.size_multiplier == Decimal("2.0")


def test_calibrate_one_returns_none_when_strategy_not_found():
    registry = StrategyRegistry()
    store = MagicMock()
    engine = CalibrationEngine(registry=registry, store=store)

    result = engine.calibrate_one("nonexistent", "AAPL")
    assert result is None


def test_calibrate_one_returns_none_on_insufficient_bars():
    registry = StrategyRegistry()
    strategy = _MockStrategy()
    registry.register(strategy)
    store = MagicMock()
    engine = CalibrationEngine(registry=registry, store=store)

    with patch.object(engine, "_run_backtest", return_value=None):
        result = engine.calibrate_one("mock_strat", "AAPL")

    assert result is None


def test_calibrate_one_returns_calibration_result_fields():
    registry = StrategyRegistry()
    strategy = _MockStrategy()
    registry.register(strategy)
    store = MagicMock()
    engine = CalibrationEngine(registry=registry, store=store)

    mock_result = _make_backtest_result(sharpe="1.0")
    with patch.object(engine, "_run_backtest", return_value=mock_result):
        result = engine.calibrate_one("mock_strat", "AAPL")

    assert result is not None
    assert isinstance(result, CalibrationResult)
    assert result.strategy_id == "mock_strat"
    assert result.rolling_sharpe == Decimal("1.0")
    assert result.size_multiplier == Decimal("1.5")


# ---------------------------------------------------------------------------
# _tune_parameters tests
# ---------------------------------------------------------------------------

def test_tune_parameters_empty_grid_returns_zero_improvement():
    registry = StrategyRegistry()
    store = MagicMock()
    engine = CalibrationEngine(registry=registry, store=store)
    strategy = _MockStrategy()

    best_params, improvement = engine._tune_parameters(strategy, "AAPL")

    assert best_params == {}
    assert improvement == Decimal("0")


def test_tune_parameters_finds_better_combo():
    """Grid search picks the param combo that produces the highest Sharpe."""
    registry = StrategyRegistry()
    store = MagicMock()
    engine = CalibrationEngine(registry=registry, store=store)

    @dataclass
    class _GridStrategy(Strategy):
        strategy_id: str = "grid_strat"
        symbol: str = "AAPL"
        bars_needed: int = 2
        bar_size: str = "5 mins"
        threshold: Decimal = Decimal("0.001")

        PARAM_GRID: dict = dataclasses.field(
            default_factory=lambda: {"threshold": ["0.001", "0.002", "0.003"]},
            init=False,
            repr=False,
            compare=False,
        )

        def on_bars(self, bars: list[Bar]) -> Signal | None:
            return None

    strategy = _GridStrategy()

    sharpe_map = {
        Decimal("0.001"): Decimal("0.8"),
        Decimal("0.002"): Decimal("1.5"),
        Decimal("0.003"): Decimal("1.0"),
    }

    def fake_run_backtest(s: Strategy, symbol: str) -> BacktestResult:
        sharpe = sharpe_map.get(s.threshold, Decimal("0.5"))
        return _make_backtest_result(sharpe=str(sharpe))

    with patch.object(engine, "_run_backtest", side_effect=fake_run_backtest):
        best_params, improvement = engine._tune_parameters(strategy, "AAPL")

    assert best_params["threshold"] == Decimal("0.002")
    assert improvement == Decimal("0.7")
