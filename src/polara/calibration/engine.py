"""CalibrationEngine — tunes strategy sizing and parameters using rolling backtest."""
import asyncio
import dataclasses
import itertools
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from polara.backtester.engine import Backtester
from polara.backtester.schemas import BacktestResult
from polara.calibration.schemas import CalibrationResult
from polara.market_data.store import BarStore
from polara.research_engine.base import Strategy
from polara.research_engine.registry import StrategyRegistry


@dataclass
class CalibrationEngine:
    registry: StrategyRegistry
    store: BarStore
    lookback_bars: int = 200

    def _size_multiplier(self, sharpe: Decimal) -> Decimal:
        if sharpe >= Decimal("1.5"):
            return Decimal("2.0")
        if sharpe >= Decimal("1.0"):
            return Decimal("1.5")
        if sharpe >= Decimal("0.5"):
            return Decimal("1.0")
        return Decimal("0.5")

    def _run_backtest(self, strategy: Strategy, symbol: str) -> BacktestResult | None:
        try:
            backtester = Backtester(strategy=strategy, store=self.store)
            return backtester.run(
                symbol=symbol,
                bar_size=strategy.bar_size,
                lookback_bars=self.lookback_bars,
            )
        except ValueError:
            return None

    def _tune_parameters(
        self, strategy: Strategy, symbol: str
    ) -> tuple[dict, Decimal]:
        param_grid: dict = (
            getattr(type(strategy), "PARAM_GRID", None) or getattr(strategy, "PARAM_GRID", {})
        )
        if not param_grid:
            return ({}, Decimal("0"))

        current_params = {
            f.name: getattr(strategy, f.name)
            for f in dataclasses.fields(strategy)
            if f.name in param_grid
        }

        baseline_result = self._run_backtest(strategy, symbol)
        if baseline_result is None:
            return ({}, Decimal("0"))

        baseline_sharpe = baseline_result.sharpe_ratio

        field_names = list(param_grid.keys())
        grid_values = [param_grid[k] for k in field_names]

        best_sharpe = baseline_sharpe
        best_combo: dict = current_params

        for combo_values in itertools.product(*grid_values):
            combo: dict = {}
            for name, val in zip(field_names, combo_values):
                actual_type = type(getattr(strategy, name))
                if actual_type is Decimal:
                    combo[name] = Decimal(str(val))
                elif actual_type is int:
                    combo[name] = int(val)
                else:
                    combo[name] = val

            candidate = dataclasses.replace(strategy, **combo)
            result = self._run_backtest(candidate, symbol)
            if result is not None and result.sharpe_ratio > best_sharpe:
                best_sharpe = result.sharpe_ratio
                best_combo = combo

        improvement = best_sharpe - baseline_sharpe
        return (best_combo, improvement)

    def calibrate_one(self, strategy_id: str, symbol: str) -> CalibrationResult | None:
        try:
            strategy = self.registry.get(strategy_id)
        except KeyError:
            return None

        _pg = getattr(type(strategy), "PARAM_GRID", None) or getattr(strategy, "PARAM_GRID", {})
        param_fields = set(_pg.keys())
        prev_params = {
            f.name: str(getattr(strategy, f.name))
            for f in dataclasses.fields(strategy)
            if f.name in param_fields
        }

        result = self._run_backtest(strategy, symbol)
        if result is None:
            return None

        rolling_sharpe = result.sharpe_ratio
        size_mult = self._size_multiplier(rolling_sharpe)

        best_params_raw, improvement = self._tune_parameters(strategy, symbol)
        best_params = {k: str(v) for k, v in best_params_raw.items()}

        strategy.size_multiplier = size_mult
        if best_params_raw:
            for field_name, val in best_params_raw.items():
                setattr(strategy, field_name, val)

        return CalibrationResult(
            strategy_id=strategy_id,
            calibrated_at=datetime.now(UTC),
            bar_size=strategy.bar_size,
            lookback_bars=self.lookback_bars,
            rolling_sharpe=rolling_sharpe,
            size_multiplier=size_mult,
            prev_params=prev_params,
            best_params=best_params,
            param_sharpe_improvement=improvement,
        )

    async def calibrate_all(self, symbol: str) -> list[CalibrationResult]:
        results = []
        for strategy in self.registry.get_all():
            result = await asyncio.to_thread(self.calibrate_one, strategy.strategy_id, symbol)
            if result is not None:
                results.append(result)
        return results


__all__ = ["CalibrationEngine"]
