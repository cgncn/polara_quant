"""Tests for TradeService and DashboardService."""
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from polara.dashboard.dashboard_service import DashboardService, _strategy_row
from polara.dashboard.trade_service import TradeService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db_factory(rows=None, fetchone_row=None):
    """Return an async session factory whose execute() returns canned rows."""
    session = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = rows or []
    result.fetchone.return_value = fetchone_row
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory, session


# ---------------------------------------------------------------------------
# TradeService
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_open_trade_inserts_row():
    factory, session = _make_db_factory()
    svc = TradeService(db_session_factory=factory)
    await svc.open_trade(
        entry_order_id="ord-001",
        strategy_id="ma-crossover-aapl",
        symbol="AAPL",
        side="buy",
        quantity=Decimal("10"),
        entry_price=Decimal("150.00"),
        commission=Decimal("1.00"),
        entry_at=datetime(2024, 1, 15, 10, 0, tzinfo=UTC),
    )
    session.execute.assert_called_once()
    session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_close_trade_calculates_pnl():
    entry_row = MagicMock()
    entry_row.quantity = "10"
    entry_row.entry_price = "150.00"
    entry_row.commission = "1.00"
    entry_row.side = "buy"

    factory, session = _make_db_factory()
    # First execute (GET_OPEN_TRADE) returns the entry row; subsequent ones succeed
    result_get = MagicMock()
    result_get.fetchone.return_value = entry_row
    result_noop = MagicMock()
    result_noop.fetchone.return_value = None
    session.execute = AsyncMock(side_effect=[result_get, result_noop, result_noop])

    svc = TradeService(db_session_factory=factory)
    await svc.close_trade(
        entry_order_id="ord-001",
        exit_order_id="ord-002",
        exit_price=Decimal("155.00"),
        commission=Decimal("1.00"),
        exit_at=datetime(2024, 1, 15, 14, 0, tzinfo=UTC),
    )
    # 3 executes: GET_OPEN_TRADE, CLOSE_TRADE, UPSERT_DAILY_SUMMARY
    assert session.execute.call_count == 3
    session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_close_trade_noop_when_no_open_trade():
    factory, session = _make_db_factory(fetchone_row=None)
    svc = TradeService(db_session_factory=factory)
    await svc.close_trade(
        entry_order_id="nonexistent",
        exit_order_id="ord-002",
        exit_price=Decimal("155.00"),
        commission=Decimal("1.00"),
        exit_at=datetime(2024, 1, 15, 14, 0, tzinfo=UTC),
    )
    # Only the GET query runs; no CLOSE or SUMMARY
    assert session.execute.call_count == 1
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_record_nav_upserts_daily_summary():
    factory, session = _make_db_factory()
    svc = TradeService(db_session_factory=factory)
    await svc.record_nav(Decimal("100000"), datetime(2024, 1, 15, 16, 0, tzinfo=UTC))
    assert session.execute.call_count == 2  # ENSURE + UPDATE_NAV
    session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# DashboardService
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_today_summary_no_data():
    factory, _ = _make_db_factory(rows=[], fetchone_row=None)
    svc = DashboardService(db_session_factory=factory)
    result = await svc.today_summary()
    assert result["net_pnl"] == "0"
    assert result["trade_count"] == 0
    assert result["trades"] == []


@pytest.mark.asyncio
async def test_pnl_history_empty():
    factory, _ = _make_db_factory(rows=[])
    svc = DashboardService(db_session_factory=factory)
    result = await svc.pnl_history(days=30)
    assert result == []


@pytest.mark.asyncio
async def test_trades_filtered_no_filters():
    factory, session = _make_db_factory(rows=[])
    svc = DashboardService(db_session_factory=factory)
    result = await svc.trades_filtered()
    assert result == []
    session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_trades_filtered_with_strategy():
    factory, session = _make_db_factory(rows=[])
    svc = DashboardService(db_session_factory=factory)
    await svc.trades_filtered(strategy_id="ma-crossover-aapl")
    call_args = session.execute.call_args
    sql = str(call_args[0][0])
    assert "strategy_id" in sql


@pytest.mark.asyncio
async def test_strategy_performance_empty():
    factory, _ = _make_db_factory(rows=[])
    svc = DashboardService(db_session_factory=factory)
    result = await svc.strategy_performance()
    assert result == []


@pytest.mark.asyncio
async def test_symbol_performance_empty():
    factory, _ = _make_db_factory(rows=[])
    svc = DashboardService(db_session_factory=factory)
    result = await svc.symbol_performance()
    assert result == []


# ---------------------------------------------------------------------------
# _strategy_row helper
# ---------------------------------------------------------------------------

def test_strategy_row_profit_factor():
    row = MagicMock()
    row.strategy_id = "ma-crossover-aapl"
    row.symbol = None
    row.trade_count = 10
    row.win_count = 6
    row.net_pnl = 500.0
    row.avg_win = 100.0
    row.avg_loss = -50.0
    row.gross_win = 600.0
    row.gross_loss = 100.0
    result = _strategy_row(row)
    assert result["strategy_id"] == "ma-crossover-aapl"
    assert result["win_rate"] == 60.0
    assert result["profit_factor"] == "6.0"


def test_strategy_row_zero_gross_loss():
    row = MagicMock()
    row.strategy_id = "test"
    row.symbol = None
    row.trade_count = 5
    row.win_count = 5
    row.net_pnl = 250.0
    row.avg_win = 50.0
    row.avg_loss = None
    row.gross_win = 250.0
    row.gross_loss = 0.0
    result = _strategy_row(row)
    assert result["profit_factor"] is None


def test_strategy_row_win_rate_zero_trades():
    row = MagicMock()
    row.strategy_id = "empty"
    row.symbol = None
    row.trade_count = 0
    row.win_count = 0
    row.net_pnl = 0.0
    row.avg_win = None
    row.avg_loss = None
    row.gross_win = 0.0
    row.gross_loss = 0.0
    result = _strategy_row(row)
    assert result["win_rate"] == 0.0
