import asyncio
import os
import tempfile
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine


def _alembic_cfg(db_path: str) -> Config:
    """Return an Alembic Config pointing at a temp DB."""
    url = f"sqlite+aiosqlite:///{db_path}"
    cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.set_main_option("DATABASE_URL", url)
    # Override via os.environ so env.py picks it up — caller must restore
    os.environ["DATABASE_URL"] = url
    return cfg


async def _get_tables(db_url: str) -> list[str]:
    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        tables = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_table_names()
        )
    await engine.dispose()
    return tables


async def _get_columns(db_url: str, table: str) -> list[str]:
    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        cols = await conn.run_sync(
            lambda sync_conn: [
                c["name"] for c in inspect(sync_conn).get_columns(table)
            ]
        )
    await engine.dispose()
    return cols


def test_upgrade_creates_expected_tables() -> None:
    original = os.environ.get("DATABASE_URL")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        cfg = _alembic_cfg(db_path)
        command.upgrade(cfg, "head")
        tables = asyncio.run(_get_tables(f"sqlite+aiosqlite:///{db_path}"))
        assert "strategies" in tables
        assert "strategy_versions" in tables
        assert "jobs" in tables
        assert "alembic_version" in tables
    finally:
        os.unlink(db_path)
        if original is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original


def test_upgrade_is_idempotent() -> None:
    original = os.environ.get("DATABASE_URL")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        cfg = _alembic_cfg(db_path)
        command.upgrade(cfg, "head")
        # Running upgrade again must not raise
        command.upgrade(cfg, "head")
    finally:
        os.unlink(db_path)
        if original is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original


def test_downgrade_removes_tables() -> None:
    original = os.environ.get("DATABASE_URL")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        cfg = _alembic_cfg(db_path)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        tables = asyncio.run(_get_tables(f"sqlite+aiosqlite:///{db_path}"))
        assert "strategies" not in tables
        assert "strategy_versions" not in tables
        assert "jobs" not in tables
    finally:
        os.unlink(db_path)
        if original is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original


def test_upgrade_creates_broker_tables() -> None:
    original = os.environ.get("DATABASE_URL")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        cfg = _alembic_cfg(db_path)
        command.upgrade(cfg, "head")
        tables = asyncio.run(_get_tables(f"sqlite+aiosqlite:///{db_path}"))
        assert "orders" in tables
        assert "fills" in tables
        assert "positions" in tables
        assert "account_snapshots" in tables
    finally:
        os.unlink(db_path)
        if original is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original


def test_upgrade_creates_signal_orders_table() -> None:
    original = os.environ.get("DATABASE_URL")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        cfg = _alembic_cfg(db_path)
        command.upgrade(cfg, "head")
        tables = asyncio.run(_get_tables(f"sqlite+aiosqlite:///{db_path}"))
        assert "signal_orders" in tables
    finally:
        os.unlink(db_path)
        if original is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original


def test_downgrade_0002_removes_signal_orders_table() -> None:
    original = os.environ.get("DATABASE_URL")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        cfg = _alembic_cfg(db_path)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0002")
        tables = asyncio.run(_get_tables(f"sqlite+aiosqlite:///{db_path}"))
        assert "signal_orders" not in tables
        # Phase-2 tables must still be present
        assert "orders" in tables
        assert "fills" in tables
        assert "positions" in tables
        assert "account_snapshots" in tables
    finally:
        os.unlink(db_path)
        if original is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original


def test_downgrade_0001_removes_broker_tables() -> None:
    original = os.environ.get("DATABASE_URL")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        cfg = _alembic_cfg(db_path)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0001")
        tables = asyncio.run(_get_tables(f"sqlite+aiosqlite:///{db_path}"))
        assert "orders" not in tables
        assert "fills" not in tables
        assert "positions" not in tables
        assert "account_snapshots" not in tables
        # Phase-1 tables must still be present
        assert "strategies" in tables
        assert "strategy_versions" in tables
        assert "jobs" in tables
    finally:
        os.unlink(db_path)
        if original is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original


def test_upgrade_creates_backtest_results_table() -> None:
    """Phase 4 migration creates the backtest_results table."""
    original = os.environ.get("DATABASE_URL")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        cfg = _alembic_cfg(db_path)
        command.upgrade(cfg, "head")
        tables = asyncio.run(_get_tables(f"sqlite+aiosqlite:///{db_path}"))
        assert "backtest_results" in tables
    finally:
        os.unlink(db_path)
        if original is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original


def test_downgrade_0003_removes_backtest_results_table() -> None:
    """Downgrading to 0003 removes backtest_results."""
    original = os.environ.get("DATABASE_URL")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        cfg = _alembic_cfg(db_path)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0003")
        tables = asyncio.run(_get_tables(f"sqlite+aiosqlite:///{db_path}"))
        assert "backtest_results" not in tables
        # Phase-3 tables must still exist
        assert "signal_orders" in tables
    finally:
        os.unlink(db_path)
        if original is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original


def test_strategies_status_accepts_live_after_migration() -> None:
    """After Phase 4 migration, strategies.status='live' is a valid value."""
    import asyncio as _asyncio

    async def _insert_live(db_url: str) -> None:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text as _text
        engine = create_async_engine(db_url)
        async with engine.begin() as conn:
            await conn.execute(_text(
                "INSERT INTO strategies (id, name, status, created_at) "
                "VALUES ('s1', 'test', 'live', '2026-01-01T00:00:00')"
            ))
        await engine.dispose()

    original = os.environ.get("DATABASE_URL")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        cfg = _alembic_cfg(db_path)
        command.upgrade(cfg, "head")
        # Should not raise
        _asyncio.run(_insert_live(f"sqlite+aiosqlite:///{db_path}"))
    finally:
        os.unlink(db_path)
        if original is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original


def test_0005_bracket_orders_table_created() -> None:
    original = os.environ.get("DATABASE_URL")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        cfg = _alembic_cfg(db_path)
        command.upgrade(cfg, "head")
        tables = asyncio.run(_get_tables(f"sqlite+aiosqlite:///{db_path}"))
        assert "bracket_orders" in tables
    finally:
        os.unlink(db_path)
        if original is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original


def test_0005_signal_orders_has_stop_price_column() -> None:
    original = os.environ.get("DATABASE_URL")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        cfg = _alembic_cfg(db_path)
        command.upgrade(cfg, "head")
        cols = asyncio.run(
            _get_columns(f"sqlite+aiosqlite:///{db_path}", "signal_orders")
        )
        assert "stop_price" in cols
        assert "take_profit_price" in cols
    finally:
        os.unlink(db_path)
        if original is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original


def test_0005_downgrade_removes_bracket_orders() -> None:
    original = os.environ.get("DATABASE_URL")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        cfg = _alembic_cfg(db_path)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0004")
        tables = asyncio.run(_get_tables(f"sqlite+aiosqlite:///{db_path}"))
        assert "bracket_orders" not in tables
    finally:
        os.unlink(db_path)
        if original is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original
