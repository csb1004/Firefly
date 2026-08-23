"""add configurable new user draw bonus

Revision ID: 20260824_0005
Revises: 20260823_0004
Create Date: 2026-08-24 04:30:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260824_0005"
down_revision: Union[str, Sequence[str], None] = "20260823_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "draw_settings",
        sa.Column("new_user_bonus_tickets", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_draw_settings_new_user_bonus_range",
        "draw_settings",
        "new_user_bonus_tickets >= 0 AND new_user_bonus_tickets <= 10000",
    )


def downgrade() -> None:
    op.drop_constraint("ck_draw_settings_new_user_bonus_range", "draw_settings", type_="check")
    op.drop_column("draw_settings", "new_user_bonus_tickets")
