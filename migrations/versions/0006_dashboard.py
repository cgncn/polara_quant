"""Dashboard: trades + daily_summary tables

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-26
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trades",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("strategy_id", sa.Text, nullable=False),
        sa.Column("symbol", sa.Text, nullable=False),
        sa.Column("side", sa.Text, nullable=False),
        sa.Column("quantity", sa.Text, nullable=False),
        sa.Column("entry_price", sa.Text, nullable=False),
        sa.Column("exit_price", sa.Text, nullable=True),
        sa.Column("entry_at", sa.Text, nullable=False),
        sa.Column("exit_at", sa.Text, nullable=True),
        sa.Column("realised_pnl", sa.Text, nullable=True),
        sa.Column("commission", sa.Text, nullable=False, server_default="0"),
        sa.Column("status", sa.Text, nullable=False, server_default="open"),
        sa.Column("trade_date", sa.Text, nullable=False),
        sa.Column("entry_order_id", sa.Text, nullable=False),
        sa.Column("exit_order_id", sa.Text, nullable=True),
    )
    op.create_index("ix_trades_strategy_id", "trades", ["strategy_id"])
    op.create_index("ix_trades_symbol", "trades", ["symbol"])
    op.create_index("ix_trades_trade_date", "trades", ["trade_date"])
    op.create_index("ix_trades_status", "trades", ["status"])

    op.create_table(
        "daily_summary",
        sa.Column("trade_date", sa.Text, primary_key=True),
        sa.Column("net_pnl", sa.Text, nullable=False, server_default="0"),
        sa.Column("trade_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("win_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("gross_win", sa.Text, nullable=False, server_default="0"),
        sa.Column("gross_loss", sa.Text, nullable=False, server_default="0"),
        sa.Column("start_nav", sa.Text, nullable=True),
        sa.Column("end_nav", sa.Text, nullable=True),
        sa.Column("updated_at", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_index("ix_trades_status", "trades")
    op.drop_index("ix_trades_trade_date", "trades")
    op.drop_index("ix_trades_symbol", "trades")
    op.drop_index("ix_trades_strategy_id", "trades")
    op.drop_table("trades")
    op.drop_table("daily_summary")
