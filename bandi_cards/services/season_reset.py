from __future__ import annotations

import json
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from ..models import (
    AdminAudit,
    Card,
    CardSet,
    CatalogUnlock,
    DailyDrawAllowance,
    DiscardEvent,
    DrawBatch,
    DrawHistory,
    DrawSetting,
    DrawState,
    DrawWallet,
    FiveStarEvent,
    Gift,
    ImageCleanup,
    Inventory,
    NotificationOutbox,
    ProbabilityAudit,
    RaritySetting,
    TradeOffer,
    TradeRequest,
    TradeRoom,
    User,
    WebSocketTicket,
    utcnow,
)
from .probabilities import base_probabilities, validate_probability_configuration


CONFIRMATION_TEXT = "영호 가챠 시즌 초기화"
ADVISORY_LOCK_NAMESPACE = 1947147369
ADVISORY_LOCK_OPERATION = 1


class SeasonResetLockUnavailable(RuntimeError):
    """Raised when another process owns the database reset lock."""


class SeasonResetConfigurationInvalid(RuntimeError):
    """Raised before reset when preserved draw configuration is unusable."""


RESET_MODELS = (
    FiveStarEvent,
    DrawHistory,
    DrawBatch,
    TradeOffer,
    TradeRequest,
    TradeRoom,
    Gift,
    DiscardEvent,
    Inventory,
    CatalogUnlock,
    DrawState,
    DailyDrawAllowance,
    DrawWallet,
    WebSocketTicket,
    NotificationOutbox,
    ProbabilityAudit,
    AdminAudit,
)


def _load_and_validate_configuration(db: Session) -> DrawSetting:
    setting = db.get(DrawSetting, 1)
    if setting is None:
        raise SeasonResetConfigurationInvalid("뽑기 지급 설정을 찾을 수 없습니다.")
    try:
        validate_probability_configuration(db, base_probabilities(db))
    except HTTPException as exc:
        raise SeasonResetConfigurationInvalid(str(exc.detail)) from exc
    return setting


def _acquire_postgres_locks(db: Session) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    locked = db.scalar(
        text("SELECT pg_try_advisory_xact_lock(:namespace, :operation)"),
        {"namespace": ADVISORY_LOCK_NAMESPACE, "operation": ADVISORY_LOCK_OPERATION},
    )
    if not locked:
        raise SeasonResetLockUnavailable
    db.execute(text("LOCK TABLE users, draw_settings IN SHARE MODE"))
    db.execute(
        text(
            "LOCK TABLE five_star_events, draw_history, draw_batches, "
            "trade_offers, trade_requests, trade_rooms, gifts, discard_events, "
            "inventory, catalog_unlocks, draw_states, daily_draw_allowances, "
            "draw_wallets, websocket_tickets, notification_outbox, "
            "probability_audit, admin_audit IN ACCESS EXCLUSIVE MODE"
        )
    )


def _row_count(db: Session, model) -> int:
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def _delete_counts(db: Session) -> dict[str, int]:
    return {model.__tablename__: _row_count(db, model) for model in RESET_MODELS}


def _preserved_snapshot(db: Session, setting: DrawSetting) -> dict:
    return {
        "users": _row_count(db, User),
        "cards": _row_count(db, Card),
        "card_sets": _row_count(db, CardSet),
        "rarity_settings": _row_count(db, RaritySetting),
        "image_cleanup": _row_count(db, ImageCleanup),
        "draw_settings": {
            "daily_draws": int(setting.daily_draws),
            "new_user_bonus_tickets": int(setting.new_user_bonus_tickets),
        },
    }


def _impact_snapshot(db: Session, setting: DrawSetting, *, grant_key: str) -> dict:
    delete_counts = _delete_counts(db)
    inventory_copies = int(db.scalar(select(func.coalesce(func.sum(Inventory.quantity), 0))) or 0)
    eligible_users = _row_count(db, User)
    tickets_per_user = int(setting.new_user_bonus_tickets)
    return {
        "delete_counts": delete_counts,
        "summary": {
            "inventory_copies": inventory_copies,
            "trade_records": sum(delete_counts[name] for name in ("trade_rooms", "trade_offers", "trade_requests")),
            "audit_records": delete_counts["probability_audit"] + delete_counts["admin_audit"],
        },
        "preserved": _preserved_snapshot(db, setting),
        "grant": {
            grant_key: eligible_users,
            "tickets_per_user": tickets_per_user,
            "total_tickets": eligible_users * tickets_per_user,
        },
    }


def preview_season_reset(db: Session) -> dict:
    setting = _load_and_validate_configuration(db)
    return _impact_snapshot(db, setting, grant_key="eligible_users")


def _grant_bonus_wallets(db: Session, tickets_per_user: int, now: datetime) -> int:
    user_ids = list(db.scalars(select(User.id).order_by(User.id)).all())
    if tickets_per_user > 0:
        db.add_all(
            DrawWallet(user_id=user_id, bonus_tickets=tickets_per_user, updated_at=now)
            for user_id in user_ids
        )
        db.flush()
    return len(user_ids)


def _append_reset_audit(
    db: Session,
    *,
    admin_id: int,
    completed_at: datetime,
    details: dict,
) -> AdminAudit:
    completed_at_text = completed_at.isoformat()
    audit = AdminAudit(
        admin_id=admin_id,
        action="season.reset",
        target_type="season",
        target_id=completed_at_text,
        details_json=json.dumps(details, ensure_ascii=False, sort_keys=True),
        created_at=completed_at,
    )
    db.add(audit)
    db.flush()
    return audit


def execute_season_reset(db: Session, admin_id: int) -> dict:
    _acquire_postgres_locks(db)
    setting = _load_and_validate_configuration(db)
    snapshot = _impact_snapshot(db, setting, grant_key="granted_users")
    completed_at = utcnow()

    for model in RESET_MODELS:
        db.execute(delete(model))

    granted_users = _grant_bonus_wallets(
        db,
        snapshot["grant"]["tickets_per_user"],
        completed_at,
    )
    snapshot["grant"]["granted_users"] = granted_users
    snapshot["grant"]["total_tickets"] = granted_users * snapshot["grant"]["tickets_per_user"]
    audit = _append_reset_audit(
        db,
        admin_id=admin_id,
        completed_at=completed_at,
        details={
            "delete_counts": snapshot["delete_counts"],
            "grant": snapshot["grant"],
            "preserved": snapshot["preserved"],
        },
    )
    return {
        **snapshot,
        "completed_at": completed_at.isoformat(),
        "audit_id": audit.id,
    }
