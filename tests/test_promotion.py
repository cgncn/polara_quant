"""Tests for PromotionGate."""
from unittest.mock import AsyncMock

import pytest

from polara.backtester.service import BacktestService
from polara.research_engine.promotion import PromotionError, PromotionGate
from polara.research_engine.status_service import StrategyStatusService


def make_gate(has_passing: bool = True, current_status: str = "paper"):
    status_svc = AsyncMock(spec=StrategyStatusService)
    status_svc.get_status = AsyncMock(return_value=current_status)
    status_svc.set_status = AsyncMock()

    backtest_svc = AsyncMock(spec=BacktestService)
    backtest_svc.has_passing_result = AsyncMock(return_value=has_passing)

    gate = PromotionGate(status_service=status_svc, backtest_service=backtest_svc)
    return gate, status_svc, backtest_svc


# ── promote ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_promote_succeeds_paper_to_live():
    """Passing backtest + paper status → set_status("live") called."""
    gate, status_svc, _ = make_gate(has_passing=True, current_status="paper")
    await gate.promote("strat-1")
    status_svc.set_status.assert_called_once_with("strat-1", "live")


@pytest.mark.asyncio
async def test_promote_succeeds_paused_to_live():
    """Passing backtest + paused status → set_status("live") called."""
    gate, status_svc, _ = make_gate(has_passing=True, current_status="paused")
    await gate.promote("strat-1")
    status_svc.set_status.assert_called_once_with("strat-1", "live")


@pytest.mark.asyncio
async def test_promote_fails_no_passing_backtest():
    """No passing backtest → PromotionError raised before checking status."""
    gate, status_svc, _ = make_gate(has_passing=False, current_status="paper")
    with pytest.raises(PromotionError, match="no passing backtest result"):
        await gate.promote("strat-1")
    status_svc.set_status.assert_not_called()


@pytest.mark.asyncio
async def test_promote_fails_status_inactive():
    """Passing backtest but status=inactive → PromotionError."""
    gate, status_svc, _ = make_gate(has_passing=True, current_status="inactive")
    with pytest.raises(PromotionError, match="paper or paused"):
        await gate.promote("strat-1")
    status_svc.set_status.assert_not_called()


@pytest.mark.asyncio
async def test_promote_fails_already_live():
    """Passing backtest but status=live → PromotionError."""
    gate, status_svc, _ = make_gate(has_passing=True, current_status="live")
    with pytest.raises(PromotionError, match="paper or paused"):
        await gate.promote("strat-1")
    status_svc.set_status.assert_not_called()


# ── demote ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_demote_succeeds_live_to_paper():
    """Status=live → set_status("paper") called."""
    gate, status_svc, _ = make_gate(current_status="live")
    await gate.demote("strat-1")
    status_svc.set_status.assert_called_once_with("strat-1", "paper")


@pytest.mark.asyncio
async def test_demote_fails_status_paper():
    """Status=paper → PromotionError on demote."""
    gate, status_svc, _ = make_gate(current_status="paper")
    with pytest.raises(PromotionError, match="is not live"):
        await gate.demote("strat-1")
    status_svc.set_status.assert_not_called()


@pytest.mark.asyncio
async def test_demote_fails_status_inactive():
    """Status=inactive → PromotionError on demote."""
    gate, status_svc, _ = make_gate(current_status="inactive")
    with pytest.raises(PromotionError, match="is not live"):
        await gate.demote("strat-1")
    status_svc.set_status.assert_not_called()
