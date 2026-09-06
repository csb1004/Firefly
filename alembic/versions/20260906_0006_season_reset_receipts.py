"""add durable season reset receipts

Revision ID: 20260906_0006
Revises: 20260824_0005
Create Date: 2026-09-06 11:25:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260906_0006"
down_revision: Union[str, Sequence[str], None] = "20260824_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "season_reset_receipts",
        sa.Column("operation_id", sa.String(length=64), nullable=False),
        sa.Column("admin_id", sa.Integer(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["admin_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("operation_id"),
    )
    op.create_index(
        op.f("ix_season_reset_receipts_admin_id"),
        "season_reset_receipts",
        ["admin_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_season_reset_receipts_admin_id"), table_name="season_reset_receipts")
    op.drop_table("season_reset_receipts")
