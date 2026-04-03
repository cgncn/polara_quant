"""Tests for StrategyStatusService."""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from polara.research_engine.status_service import StrategyStatusService


@pytest.fixture
async def db_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE strategies (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'inactive'
                    CHECK (status IN ('inactive', 'paper', 'paused', 'live')),
                created_at TEXT NOT NULL
            )
        """))
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def svc(db_factory):
    return StrategyStatusService(db_session_factory=db_factory)


# ── get_status ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_status_none_when_no_row(svc):
    result = await svc.get_status("nonexistent-strategy")
    assert result is None


# ── ensure_registered ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ensure_registered_creates_row(svc):
    await svc.ensure_registered("strat-1", name="Test Strategy")
    status = await svc.get_status("strat-1")
    assert status == "paper"


@pytest.mark.asyncio
async def test_ensure_registered_idempotent(svc):
    await svc.ensure_registered("strat-1", name="Test Strategy")
    await svc.ensure_registered("strat-1", name="Test Strategy")  # second call should not error
    status = await svc.get_status("strat-1")
    assert status == "paper"


# ── set_status ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_status_updates_row(svc):
    await svc.ensure_registered("strat-2", name="Strategy 2")
    await svc.set_status("strat-2", "live")
    status = await svc.get_status("strat-2")
    assert status == "live"


@pytest.mark.asyncio
async def test_set_status_raises_value_error_when_not_found(svc):
    with pytest.raises(ValueError, match="not found in DB"):
        await svc.set_status("ghost-strategy", "paper")


@pytest.mark.asyncio
async def test_all_statuses_accepted(svc):
    await svc.ensure_registered("strat-3", name="Strategy 3", status="inactive")
    for status in ("inactive", "paper", "paused", "live"):
        await svc.set_status("strat-3", status)
        result = await svc.get_status("strat-3")
        assert result == status


# ── ensure_registered does not overwrite ─────────────────────────────────────


@pytest.mark.asyncio
async def test_ensure_registered_does_not_overwrite_existing(svc):
    """If a row already exists, ensure_registered must leave the current status intact."""
    await svc.ensure_registered("strat-4", name="Strategy 4", status="paper")
    await svc.set_status("strat-4", "live")
    # Call ensure_registered again with a different default status; must not overwrite.
    await svc.ensure_registered("strat-4", name="Strategy 4", status="paper")
    status = await svc.get_status("strat-4")
    assert status == "live"
