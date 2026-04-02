"""Broker tables — orders, fills, positions, account_snapshots

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-02 00:00:00.000000
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL UNIQUE,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
            quantity TEXT NOT NULL,
            limit_price TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'submitted', 'filled', 'cancelled', 'error')),
            ib_order_id INTEGER,
            strategy_id TEXT NOT NULL,
            submitted_at TEXT NOT NULL,
            filled_at TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS fills (
            id TEXT PRIMARY KEY,
            fill_id TEXT NOT NULL UNIQUE,
            order_id TEXT NOT NULL REFERENCES orders(order_id),
            symbol TEXT NOT NULL,
            side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
            filled_quantity TEXT NOT NULL,
            fill_price TEXT NOT NULL,
            commission TEXT NOT NULL,
            filled_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL UNIQUE,
            quantity TEXT NOT NULL,
            avg_cost TEXT NOT NULL,
            unrealised_pnl TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS account_snapshots (
            id TEXT PRIMARY KEY,
            net_liquidation TEXT NOT NULL,
            cash TEXT NOT NULL,
            unrealised_pnl TEXT NOT NULL,
            realised_pnl TEXT NOT NULL,
            snapshot_at TEXT NOT NULL
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS account_snapshots")
    op.execute("DROP TABLE IF EXISTS positions")
    op.execute("DROP TABLE IF EXISTS fills")
    op.execute("DROP TABLE IF EXISTS orders")
