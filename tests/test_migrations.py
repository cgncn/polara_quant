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
