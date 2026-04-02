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
    cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    # Override env.py DATABASE_URL lookup
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
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


def test_upgrade_is_idempotent() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        cfg = _alembic_cfg(db_path)
        command.upgrade(cfg, "head")
        # Running upgrade again must not raise
        command.upgrade(cfg, "head")
    finally:
        os.unlink(db_path)


def test_downgrade_removes_tables() -> None:
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
