"""split set effect count and bonus targets

Revision ID: 20260823_0004
Revises: 20260823_0003
Create Date: 2026-08-23 10:20:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260823_0004"
down_revision: Union[str, Sequence[str], None] = "20260823_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("set_effects", sa.Column("bonus_target_scope", sa.String(length=24), nullable=True))
    op.add_column("set_effects", sa.Column("bonus_target_rarity", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_set_effect_bonus_target_scope",
        "set_effects",
        "bonus_target_scope IS NULL OR bonus_target_scope IN ('set_members', 'selected_cards', 'rarity', 'collection')",
    )
    op.create_check_constraint(
        "ck_set_effect_bonus_rarity",
        "set_effects",
        "bonus_target_rarity IS NULL OR (bonus_target_rarity >= 1 AND bonus_target_rarity <= 5)",
    )
    op.create_table(
        "set_effect_bonus_target_cards",
        sa.Column("effect_id", sa.String(length=36), nullable=False),
        sa.Column("card_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["effect_id"], ["set_effects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("effect_id", "card_id"),
    )


def downgrade() -> None:
    op.drop_table("set_effect_bonus_target_cards")
    op.drop_constraint("ck_set_effect_bonus_rarity", "set_effects", type_="check")
    op.drop_constraint("ck_set_effect_bonus_target_scope", "set_effects", type_="check")
    op.drop_column("set_effects", "bonus_target_rarity")
    op.drop_column("set_effects", "bonus_target_scope")
