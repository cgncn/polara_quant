"""Phase 3: signal_orders table

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-03
"""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signal_orders",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("signal_id", sa.Text, nullable=False),
        sa.Column("order_id", sa.Text, nullable=False),
        sa.Column("strategy_id", sa.Text, nullable=False),
        sa.Column("symbol", sa.Text, nullable=False),
        sa.Column("signal_strength", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_signal_orders_signal_id", "signal_orders", ["signal_id"])
    op.create_index("ix_signal_orders_strategy_id", "signal_orders", ["strategy_id"])


def downgrade() -> None:
    op.drop_index("ix_signal_orders_strategy_id", "signal_orders")
    op.drop_index("ix_signal_orders_signal_id", "signal_orders")
    op.drop_table("signal_orders")
