"""add configurable draw tickets

Revision ID: 20260822_0002
Revises: 20260822_0001
Create Date: 2026-08-22 17:10:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260822_0002"
down_revision: Union[str, Sequence[str], None] = "20260822_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("uq_draw_user_day", "draw_history", type_="unique")
    op.add_column(
        "draw_history",
        sa.Column("ticket_source", sa.String(length=16), nullable=False, server_default="daily"),
    )
    op.create_check_constraint(
        "ck_draw_history_ticket_source",
        "draw_history",
        "ticket_source IN ('daily', 'bonus')",
    )
    op.create_table(
        "draw_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("daily_draws", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_draw_settings_singleton"),
        sa.CheckConstraint("daily_draws >= 0 AND daily_draws <= 100", name="ck_draw_settings_daily_range"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "INSERT INTO draw_settings (id, daily_draws, updated_at) VALUES (1, 1, CURRENT_TIMESTAMP)"
    )
    op.create_table(
        "draw_wallets",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("bonus_tickets", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("bonus_tickets >= 0", name="ck_draw_wallet_bonus_nonnegative"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "daily_draw_allowances",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("draw_day", sa.Date(), nullable=False),
        sa.Column("extra_draws", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("extra_draws >= 0", name="ck_daily_draw_allowance_nonnegative"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "draw_day"),
    )


def downgrade() -> None:
    op.drop_table("daily_draw_allowances")
    op.drop_table("draw_wallets")
    op.drop_table("draw_settings")
    op.drop_constraint("ck_draw_history_ticket_source", "draw_history", type_="check")
    op.drop_column("draw_history", "ticket_source")
    op.create_unique_constraint("uq_draw_user_day", "draw_history", ["user_id", "draw_day"])
