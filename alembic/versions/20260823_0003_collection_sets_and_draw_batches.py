"""add permanent catalog, set effects, discards, and draw batches

Revision ID: 20260823_0003
Revises: 20260822_0002
Create Date: 2026-08-23 10:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260823_0003"
down_revision: Union[str, Sequence[str], None] = "20260822_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "catalog_unlocks",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.String(length=36), nullable=False),
        sa.Column("unlocked_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "card_id"),
    )
    op.create_table(
        "discard_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.String(length=36), nullable=True),
        sa.Column("card_name", sa.String(length=100), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("quantity_after", sa.Integer(), nullable=False),
        sa.Column("yp_before", sa.Integer(), nullable=False),
        sa.Column("yp_after", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_discard_quantity"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_discard_user_idempotency"),
    )
    op.create_index("ix_discard_events_user_id", "discard_events", ["user_id"])
    op.create_index("ix_discard_events_card_id", "discard_events", ["card_id"])
    op.create_table(
        "draw_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("requested_count IN (1, 10)", name="ck_draw_batch_count"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_draw_batch_user_idempotency"),
    )
    op.create_index("ix_draw_batches_user_id", "draw_batches", ["user_id"])
    op.add_column("draw_history", sa.Column("batch_id", sa.String(length=36), nullable=True))
    op.add_column("draw_history", sa.Column("batch_position", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_draw_history_batch_id", "draw_history", "draw_batches", ["batch_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_draw_history_batch_id", "draw_history", ["batch_id"])

    op.create_table(
        "card_sets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_card_sets_name", "card_sets", ["name"], unique=True)
    op.create_index("ix_card_sets_active", "card_sets", ["active"])
    op.create_table(
        "card_set_members",
        sa.Column("set_id", sa.String(length=36), nullable=False),
        sa.Column("card_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["set_id"], ["card_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("set_id", "card_id"),
    )
    op.create_table(
        "set_effects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("set_id", sa.String(length=36), nullable=False),
        sa.Column("target_scope", sa.String(length=24), nullable=False),
        sa.Column("target_rarity", sa.Integer(), nullable=True),
        sa.Column("count_mode", sa.String(length=16), nullable=False),
        sa.Column("bonus_type", sa.String(length=16), nullable=False),
        sa.Column("value", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("max_count", sa.Integer(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint("target_scope IN ('set_members', 'selected_cards', 'rarity', 'collection')", name="ck_set_effect_target_scope"),
        sa.CheckConstraint("count_mode IN ('once', 'distinct', 'quantity')", name="ck_set_effect_count_mode"),
        sa.CheckConstraint("bonus_type IN ('fixed', 'percent')", name="ck_set_effect_bonus_type"),
        sa.CheckConstraint("value >= 0", name="ck_set_effect_value"),
        sa.CheckConstraint("max_count IS NULL OR max_count > 0", name="ck_set_effect_max_count"),
        sa.CheckConstraint("target_rarity IS NULL OR (target_rarity >= 1 AND target_rarity <= 5)", name="ck_set_effect_rarity"),
        sa.ForeignKeyConstraint(["set_id"], ["card_sets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_set_effects_set_id", "set_effects", ["set_id"])
    op.create_table(
        "set_effect_target_cards",
        sa.Column("effect_id", sa.String(length=36), nullable=False),
        sa.Column("card_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["effect_id"], ["set_effects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("effect_id", "card_id"),
    )

    op.execute(sa.text("""
        INSERT INTO catalog_unlocks (user_id, card_id, unlocked_at)
        SELECT unlocks.user_id, unlocks.card_id, CURRENT_TIMESTAMP
        FROM (
            SELECT user_id, card_id FROM inventory WHERE quantity > 0
            UNION
            SELECT user_id, card_id FROM draw_history WHERE card_id IS NOT NULL
            UNION
            SELECT receiver_id AS user_id, card_id FROM gifts WHERE card_id IS NOT NULL
            UNION
            SELECT CASE WHEN o.user_id = r.inviter_id THEN r.invitee_id ELSE r.inviter_id END AS user_id,
                   o.card_id
            FROM trade_rooms r
            JOIN trade_offers o ON o.room_id = r.id
            WHERE r.status = 'completed' AND o.card_id IS NOT NULL
        ) AS unlocks
    """))


def downgrade() -> None:
    op.drop_table("set_effect_target_cards")
    op.drop_index("ix_set_effects_set_id", table_name="set_effects")
    op.drop_table("set_effects")
    op.drop_table("card_set_members")
    op.drop_index("ix_card_sets_active", table_name="card_sets")
    op.drop_index("ix_card_sets_name", table_name="card_sets")
    op.drop_table("card_sets")
    op.drop_index("ix_draw_history_batch_id", table_name="draw_history")
    op.drop_constraint("fk_draw_history_batch_id", "draw_history", type_="foreignkey")
    op.drop_column("draw_history", "batch_position")
    op.drop_column("draw_history", "batch_id")
    op.drop_index("ix_draw_batches_user_id", table_name="draw_batches")
    op.drop_table("draw_batches")
    op.drop_index("ix_discard_events_card_id", table_name="discard_events")
    op.drop_index("ix_discard_events_user_id", table_name="discard_events")
    op.drop_table("discard_events")
    op.drop_table("catalog_unlocks")
