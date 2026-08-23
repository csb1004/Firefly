from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def uuid_string() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    discord_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(32), index=True)
    global_name: Mapped[str | None] = mapped_column(String(64), index=True)
    avatar_hash: Mapped[str | None] = mapped_column(String(128))
    warning_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    accepts_gifts: Mapped[bool] = mapped_column(Boolean, default=True)
    accepts_trades: Mapped[bool] = mapped_column(Boolean, default=True)
    profile_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    profile_sync_attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    profile_sync_error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WebSession(Base):
    __tablename__ = "web_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class OAuthAttempt(Base):
    __tablename__ = "oauth_attempts"

    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    verifier: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class WebSocketTicket(Base):
    __tablename__ = "websocket_tickets"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RaritySetting(Base):
    __tablename__ = "rarity_settings"
    __table_args__ = (
        CheckConstraint("rarity >= 1 AND rarity <= 5", name="ck_rarity_settings_range"),
        CheckConstraint("probability >= 0 AND probability <= 100", name="ck_rarity_probability"),
    )

    rarity: Mapped[int] = mapped_column(Integer, primary_key=True)
    probability: Mapped[float] = mapped_column(Numeric(7, 4))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Card(Base):
    __tablename__ = "cards"
    __table_args__ = (
        CheckConstraint("rarity >= 1 AND rarity <= 5", name="ck_cards_rarity"),
        CheckConstraint("yp >= 0", name="ck_cards_yp"),
        CheckConstraint("weight IS NULL OR weight > 0", name="ck_cards_weight"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    rarity: Mapped[int] = mapped_column(Integer, index=True)
    yp: Mapped[int] = mapped_column(Integer)
    weight: Mapped[float | None] = mapped_column(Numeric(12, 6))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    image_key: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CardSet(Base):
    __tablename__ = "card_sets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CardSetMember(Base):
    __tablename__ = "card_set_members"

    set_id: Mapped[str] = mapped_column(ForeignKey("card_sets.id", ondelete="CASCADE"), primary_key=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True)


class SetEffect(Base):
    __tablename__ = "set_effects"
    __table_args__ = (
        CheckConstraint(
            "target_scope IN ('set_members', 'selected_cards', 'rarity', 'collection')",
            name="ck_set_effect_target_scope",
        ),
        CheckConstraint(
            "bonus_target_scope IS NULL OR bonus_target_scope IN ('set_members', 'selected_cards', 'rarity', 'collection')",
            name="ck_set_effect_bonus_target_scope",
        ),
        CheckConstraint("count_mode IN ('once', 'distinct', 'quantity')", name="ck_set_effect_count_mode"),
        CheckConstraint("bonus_type IN ('fixed', 'percent')", name="ck_set_effect_bonus_type"),
        CheckConstraint("value >= 0", name="ck_set_effect_value"),
        CheckConstraint("max_count IS NULL OR max_count > 0", name="ck_set_effect_max_count"),
        CheckConstraint("target_rarity IS NULL OR (target_rarity >= 1 AND target_rarity <= 5)", name="ck_set_effect_rarity"),
        CheckConstraint("bonus_target_rarity IS NULL OR (bonus_target_rarity >= 1 AND bonus_target_rarity <= 5)", name="ck_set_effect_bonus_rarity"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    set_id: Mapped[str] = mapped_column(ForeignKey("card_sets.id", ondelete="CASCADE"), index=True)
    target_scope: Mapped[str] = mapped_column(String(24))
    target_rarity: Mapped[int | None] = mapped_column(Integer)
    bonus_target_scope: Mapped[str | None] = mapped_column(String(24))
    bonus_target_rarity: Mapped[int | None] = mapped_column(Integer)
    count_mode: Mapped[str] = mapped_column(String(16))
    bonus_type: Mapped[str] = mapped_column(String(16))
    value: Mapped[float] = mapped_column(Numeric(12, 4))
    max_count: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer, default=0)


class SetEffectTargetCard(Base):
    __tablename__ = "set_effect_target_cards"

    effect_id: Mapped[str] = mapped_column(ForeignKey("set_effects.id", ondelete="CASCADE"), primary_key=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True)


class SetEffectBonusTargetCard(Base):
    __tablename__ = "set_effect_bonus_target_cards"

    effect_id: Mapped[str] = mapped_column(ForeignKey("set_effects.id", ondelete="CASCADE"), primary_key=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True)


class Inventory(Base):
    __tablename__ = "inventory"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_inventory_quantity"),
        CheckConstraint("reserved_quantity >= 0", name="ck_inventory_reserved_nonnegative"),
        CheckConstraint("reserved_quantity <= quantity", name="ck_inventory_reserved_available"),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    reserved_quantity: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CatalogUnlock(Base):
    __tablename__ = "catalog_unlocks"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True)
    unlocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DiscardEvent(Base):
    __tablename__ = "discard_events"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_discard_quantity"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_discard_user_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    card_id: Mapped[str | None] = mapped_column(ForeignKey("cards.id", ondelete="SET NULL"), index=True)
    card_name: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[int] = mapped_column(Integer)
    quantity_after: Mapped[int] = mapped_column(Integer)
    yp_before: Mapped[int] = mapped_column(Integer)
    yp_after: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DrawState(Base):
    __tablename__ = "draw_states"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    pulls_since_four_plus: Mapped[int] = mapped_column(Integer, default=0)
    pulls_since_five: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DrawSetting(Base):
    __tablename__ = "draw_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_draw_settings_singleton"),
        CheckConstraint("daily_draws >= 0 AND daily_draws <= 100", name="ck_draw_settings_daily_range"),
        CheckConstraint("new_user_bonus_tickets >= 0 AND new_user_bonus_tickets <= 10000", name="ck_draw_settings_new_user_bonus_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    daily_draws: Mapped[int] = mapped_column(Integer, default=1)
    new_user_bonus_tickets: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DrawWallet(Base):
    __tablename__ = "draw_wallets"
    __table_args__ = (CheckConstraint("bonus_tickets >= 0", name="ck_draw_wallet_bonus_nonnegative"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    bonus_tickets: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DailyDrawAllowance(Base):
    __tablename__ = "daily_draw_allowances"
    __table_args__ = (CheckConstraint("extra_draws >= 0", name="ck_daily_draw_allowance_nonnegative"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    draw_day: Mapped[date] = mapped_column(Date, primary_key=True)
    extra_draws: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DrawBatch(Base):
    __tablename__ = "draw_batches"
    __table_args__ = (
        CheckConstraint("requested_count IN (1, 10)", name="ck_draw_batch_count"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_draw_batch_user_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    requested_count: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DrawHistory(Base):
    __tablename__ = "draw_history"
    __table_args__ = (
        CheckConstraint("ticket_source IN ('daily', 'bonus')", name="ck_draw_history_ticket_source"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_draw_user_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("draw_batches.id", ondelete="SET NULL"), index=True)
    batch_position: Mapped[int | None] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    card_id: Mapped[str | None] = mapped_column(ForeignKey("cards.id", ondelete="SET NULL"), index=True)
    card_name: Mapped[str] = mapped_column(String(100))
    card_rarity: Mapped[int] = mapped_column(Integer)
    card_yp: Mapped[int] = mapped_column(Integer)
    draw_day: Mapped[date] = mapped_column(Date)
    ticket_source: Mapped[str] = mapped_column(String(16), default="daily")
    idempotency_key: Mapped[str] = mapped_column(String(64))
    drawn_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class FiveStarEvent(Base):
    __tablename__ = "five_star_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    draw_id: Mapped[str] = mapped_column(ForeignKey("draw_history.id", ondelete="CASCADE"), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Gift(Base):
    __tablename__ = "gifts"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_gift_quantity"),
        UniqueConstraint("sender_id", "idempotency_key", name="uq_gift_sender_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    receiver_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    card_id: Mapped[str | None] = mapped_column(ForeignKey("cards.id", ondelete="SET NULL"))
    card_name: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[int] = mapped_column(Integer)
    sender_yp_change: Mapped[int] = mapped_column(Integer, default=0)
    receiver_yp_change: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TradeRoom(Base):
    __tablename__ = "trade_rooms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    inviter_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    invitee_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="invited", index=True)
    offer_version: Mapped[int] = mapped_column(Integer, default=0)
    inviter_accepted_version: Mapped[int | None] = mapped_column(Integer)
    invitee_accepted_version: Mapped[int | None] = mapped_column(Integer)
    reconnect_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TradeOffer(Base):
    __tablename__ = "trade_offers"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_trade_offer_quantity"),)

    room_id: Mapped[str] = mapped_column(ForeignKey("trade_rooms.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer)


class TradeRequest(Base):
    __tablename__ = "trade_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    room_id: Mapped[str] = mapped_column(ForeignKey("trade_rooms.id", ondelete="CASCADE"), index=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    target_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    card_id: Mapped[str | None] = mapped_column(ForeignKey("cards.id", ondelete="SET NULL"))
    quantity: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    recipient_discord_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProbabilityAudit(Base):
    __tablename__ = "probability_audit"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    admin_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    before_json: Mapped[str] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AdminAudit(Base):
    __tablename__ = "admin_audit"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    admin_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    details_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ImageCleanup(Base):
    __tablename__ = "image_cleanup"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    image_key: Mapped[str] = mapped_column(String(512), unique=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_error: Mapped[str | None] = mapped_column(String(500))


Index("ix_trade_active_participants", TradeRoom.status, TradeRoom.inviter_id, TradeRoom.invitee_id)
