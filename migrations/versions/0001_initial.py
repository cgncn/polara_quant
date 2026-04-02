"""Initial schema — strategies, strategy_versions, jobs

Revision ID: 0001
Revises:
Create Date: 2026-03-29 00:00:00.000000
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS strategies (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'inactive' CHECK (status IN ('inactive', 'paper', 'paused')),
            created_at TEXT NOT NULL
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_strategies_name ON strategies (name)
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS strategy_versions (
            id TEXT PRIMARY KEY,
            strategy_id TEXT NOT NULL REFERENCES strategies(id),
            version INTEGER NOT NULL,
            params_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_sv_strategy_version
            ON strategy_versions (strategy_id, version)
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            job_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'done', 'failed')),
            created_at TEXT NOT NULL DEFAULT '',
            started_at TEXT,
            finished_at TEXT,
            error_message TEXT
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS jobs")
    op.execute("DROP INDEX IF EXISTS uq_sv_strategy_version")
    op.execute("DROP TABLE IF EXISTS strategy_versions")
    op.execute("DROP INDEX IF EXISTS uq_strategies_name")
    op.execute("DROP TABLE IF EXISTS strategies")
