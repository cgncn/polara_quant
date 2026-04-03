"""Phase 4: extend strategies status CHECK to include 'live'; add backtest_results table

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-03
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Extend strategies.status CHECK constraint to include 'live'.
    # SQLite does not support ALTER TABLE ... ALTER COLUMN with new CHECK constraints,
    # so we recreate the table via raw SQL. This is also Postgres-compatible.
    op.execute("""
        CREATE TABLE strategies_new (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'inactive'
                CHECK (status IN ('inactive', 'paper', 'paused', 'live')),
            created_at TEXT NOT NULL
        )
    """)
    op.execute("INSERT INTO strategies_new SELECT * FROM strategies")
    op.execute("DROP TABLE strategies")
    op.execute("ALTER TABLE strategies_new RENAME TO strategies")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_strategies_name ON strategies (name)"
    )

    # backtest_results — all monetary/ratio values stored as TEXT (Decimal-serialised)
    op.create_table(
        "backtest_results",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("strategy_id", sa.Text, nullable=False),
        sa.Column("run_at", sa.Text, nullable=False),
        sa.Column("bar_size", sa.Text, nullable=False),
        sa.Column("num_bars", sa.Integer, nullable=False),
        sa.Column("sharpe_ratio", sa.Text, nullable=False),
        sa.Column("max_drawdown_pct", sa.Text, nullable=False),
        sa.Column("win_rate_pct", sa.Text, nullable=False),
        sa.Column("total_return_pct", sa.Text, nullable=False),
        sa.Column("num_trades", sa.Integer, nullable=False),
        sa.Column("passed", sa.Integer, nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
    )
    op.create_index(
        "ix_backtest_results_strategy_id", "backtest_results", ["strategy_id"]
    )
    op.create_index(
        "ix_backtest_results_passed",
        "backtest_results",
        ["strategy_id", "passed"],
    )


def downgrade() -> None:
    op.drop_index("ix_backtest_results_passed", "backtest_results")
    op.drop_index("ix_backtest_results_strategy_id", "backtest_results")
    op.drop_table("backtest_results")

    # Restore strategies without 'live' in CHECK; demote any live rows to 'paper'.
    op.execute("""
        CREATE TABLE strategies_old (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'inactive'
                CHECK (status IN ('inactive', 'paper', 'paused')),
            created_at TEXT NOT NULL
        )
    """)
    op.execute("""
        INSERT INTO strategies_old
        SELECT id, name,
               CASE WHEN status = 'live' THEN 'paper' ELSE status END,
               created_at
        FROM strategies
    """)
    op.execute("DROP TABLE strategies")
    op.execute("ALTER TABLE strategies_old RENAME TO strategies")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_strategies_name ON strategies (name)"
    )
