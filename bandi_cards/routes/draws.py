from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Card, DrawHistory, FiveStarEvent, Inventory, User
from ..security import require_csrf_user, require_ready_user
from ..services.card_assets import asset_store
from ..services.discord_oauth import avatar_url
from ..services.draws import collection_yp, draw_ticket_status, perform_draw, perform_draw_batch, user_probability_view
from ..services.set_effects import effective_yp, effective_yp_many


router = APIRouter(prefix="/api", tags=["draws and collection"])


def card_result(card: Card, quantity: int | None = None) -> dict:
    payload = {
        "id": card.id,
        "name": card.name,
        "rarity": card.rarity,
        "yp": card.yp,
        "image_url": asset_store.url(card.image_key),
    }
    if quantity is not None:
        payload["quantity"] = quantity
    return payload


class DrawBody(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=64)


@router.get("/draw/status")
def draw_status(user: User = Depends(require_ready_user), db: Session = Depends(get_db)) -> dict:
    probability = user_probability_view(db, user.id)
    return {
        **draw_ticket_status(db, user.id),
        **{key: probability[key] for key in ("four_remaining", "five_remaining")},
    }


@router.post("/draw")
def draw(body: DrawBody, user: User = Depends(require_csrf_user), db: Session = Depends(get_db)) -> dict:
    try:
        result = perform_draw(db, user.id, body.idempotency_key)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "동시에 처리된 뽑기가 있습니다.") from exc
    inventory = db.get(Inventory, (user.id, result.card.id))
    return {
        "draw_id": result.history.id,
        "card": card_result(result.card, inventory.quantity),
        "four_remaining": result.four_remaining,
        "five_remaining": result.five_remaining,
        "draws_remaining": result.draws_remaining,
        "daily_remaining": result.daily_remaining,
        "bonus_tickets": result.bonus_tickets,
        "repeated": result.repeated,
    }


@router.post("/draw/ten")
def draw_ten(body: DrawBody, user: User = Depends(require_csrf_user), db: Session = Depends(get_db)) -> dict:
    try:
        batch = perform_draw_batch(db, user.id, body.idempotency_key, count=10)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "동시에 처리된 뽑기가 있습니다.") from exc
    quantities = {item.card.id: db.get(Inventory, (user.id, item.card.id)).quantity for item in batch.results}
    return {
        "batch_id": batch.batch_id,
        "cards": [card_result(item.card, quantities[item.card.id]) for item in batch.results],
        "highest_rarity": max(item.card.rarity for item in batch.results),
        "four_remaining": batch.four_remaining,
        "five_remaining": batch.five_remaining,
        "draws_remaining": batch.draws_remaining,
        "daily_remaining": batch.daily_remaining,
        "bonus_tickets": batch.bonus_tickets,
        "total_yp": effective_yp(db, user.id).total_yp,
        "repeated": batch.repeated,
    }


@router.get("/probabilities/current")
def current_probabilities(user: User = Depends(require_ready_user), db: Session = Depends(get_db)) -> dict:
    return user_probability_view(db, user.id)


@router.get("/collection/me")
def my_collection(user: User = Depends(require_ready_user), db: Session = Depends(get_db)) -> dict:
    return collection(user.id, user, db)


@router.get("/users/{target_user_id}/collection")
def collection(
    target_user_id: int,
    _: User = Depends(require_ready_user),
    db: Session = Depends(get_db),
) -> dict:
    target = db.get(User, target_user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "사용자를 찾을 수 없습니다.")
    rows = db.execute(
        select(Inventory, Card)
        .join(Card, Card.id == Inventory.card_id)
        .where(Inventory.user_id == target_user_id, Inventory.quantity > 0)
        .order_by(Card.rarity.desc(), Card.name)
    ).all()
    yp = effective_yp(db, target_user_id)
    return {
        "user_id": target_user_id,
        "total_yp": yp.total_yp,
        "base_yp": yp.base_yp,
        "fixed_bonus": int(yp.fixed_bonus),
        "percent_bonus": float(yp.percent_bonus),
        "active_sets": list(yp.active_sets),
        "cards": [card_result(card, inventory.quantity) | {"available_quantity": inventory.quantity - inventory.reserved_quantity} for inventory, card in rows],
    }


@router.get("/rankings")
def rankings(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    _: User = Depends(require_ready_user),
    db: Session = Depends(get_db),
) -> dict:
    users = db.scalars(select(User).order_by(User.discord_id)).all()
    totals = effective_yp_many(db, [user.id for user in users])
    ranked = sorted(users, key=lambda item: (-totals[item.id].total_yp, item.discord_id))
    visible = ranked[(page - 1) * page_size:page * page_size]
    return {
        "page": page,
        "items": [
            {
                "rank": (page - 1) * page_size + index + 1,
                "user_id": user.id,
                "discord_id": user.discord_id,
                "username": user.username,
                "display_name": user.global_name or user.username,
                "avatar_url": avatar_url(user.discord_id, user.avatar_hash),
                "total_yp": int(total_yp),
            }
            for index, user in enumerate(visible)
            for total_yp in [totals[user.id].total_yp]
        ],
    }


@router.get("/feed/five-stars")
def five_star_feed(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: User = Depends(require_ready_user),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.execute(
        select(FiveStarEvent, User, Card)
        .join(User, User.id == FiveStarEvent.user_id)
        .join(Card, Card.id == FiveStarEvent.card_id)
        .order_by(FiveStarEvent.created_at.desc(), FiveStarEvent.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "page": page,
        "items": [
            {
                "id": event.id,
                "drawn_at": event.created_at.isoformat(),
                "user_id": user.id,
                "username": user.username,
                "display_name": user.global_name or user.username,
                "card_id": card.id,
                "card_name": card.name,
            }
            for event, user, card in rows
        ],
    }
