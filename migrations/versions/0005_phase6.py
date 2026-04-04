"""Phase 6: bracket_orders table; stop_price/take_profit_price cols on signal_orders

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-04
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # New table: bracket_orders — stores stop/take-profit child IB order IDs
    op.create_table(
        "bracket_orders",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("order_id", sa.Text, nullable=False),
        sa.Column("stop_ib_id", sa.Integer, nullable=True),
        sa.Column("take_profit_ib_id", sa.Integer, nullable=True),
        sa.Column("stop_price", sa.Text, nullable=True),
        sa.Column("take_profit_price", sa.Text, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index(
        "ix_bracket_orders_order_id", "bracket_orders", ["order_id"]
    )

    # Add nullable audit columns to signal_orders.
    # SQLite supports ADD COLUMN natively for nullable columns.
    op.add_column("signal_orders", sa.Column("stop_price", sa.Text, nullable=True))
    op.add_column(
        "signal_orders", sa.Column("take_profit_price", sa.Text, nullable=True)
    )


def downgrade() -> None:
    op.drop_index("ix_bracket_orders_order_id", "bracket_orders")
    op.drop_table("bracket_orders")

    # SQLite < 3.35 does not support DROP COLUMN — recreate signal_orders without
    # the Phase 6 columns using the same CREATE/INSERT/DROP/RENAME pattern.
    op.execute("""
        CREATE TABLE signal_orders_old (
            id            TEXT PRIMARY KEY,
            signal_id     TEXT NOT NULL,
            order_id      TEXT NOT NULL,
            strategy_id   TEXT NOT NULL,
            symbol        TEXT NOT NULL,
            signal_strength TEXT NOT NULL,
            created_at    TEXT NOT NULL
        )
    """)
    op.execute("""
        INSERT INTO signal_orders_old
            (id, signal_id, order_id, strategy_id, symbol, signal_strength, created_at)
        SELECT id, signal_id, order_id, strategy_id, symbol, signal_strength, created_at
        FROM signal_orders
    """)
    op.execute("DROP TABLE signal_orders")
    op.execute("ALTER TABLE signal_orders_old RENAME TO signal_orders")
