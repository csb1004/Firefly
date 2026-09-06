from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AdminAudit, Card, CatalogUnlock, Inventory, User
from ..season_reset import track_season_mutation
from ..security import require_admin, require_admin_csrf
from ..services.inventory import unlock_card
from ..services.set_effects import effective_yp
from .accounts import public_user
from .cards import serialize_card


router = APIRouter(prefix="/api/admin/users", tags=["collection administration"])


def require_user(db: Session, user_id: int, *, lock: bool = False) -> User:
    query = select(User).where(User.id == user_id)
    if lock:
        query = query.with_for_update()
    user = db.scalar(query)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "사용자를 찾을 수 없습니다.")
    return user


def collection_state(db: Session, user: User) -> dict:
    inventories = {item.card_id: item for item in db.scalars(select(Inventory).where(Inventory.user_id == user.id)).all()}
    unlocked = set(db.scalars(select(CatalogUnlock.card_id).where(CatalogUnlock.user_id == user.id)).all())
    cards = db.scalars(select(Card).order_by(Card.rarity.desc(), Card.name)).all()
    return {
        "user": public_user(user),
        "total_yp": effective_yp(db, user.id).total_yp,
        "cards": [
            serialize_card(card) | {
                "quantity": inventories.get(card.id).quantity if card.id in inventories else 0,
                "reserved_quantity": inventories.get(card.id).reserved_quantity if card.id in inventories else 0,
                "unlocked": card.id in unlocked,
            }
            for card in cards
        ],
    }


@router.get("/{user_id}/collection-state")
def get_collection_state(user_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    return collection_state(db, require_user(db, user_id))


class QuantityBody(BaseModel):
    quantity: int = Field(ge=0, le=1_000_000)


@router.put("/{user_id}/inventory/{card_id}")
def set_inventory_quantity(
    user_id: int,
    card_id: str,
    body: QuantityBody,
    admin: User = Depends(require_admin_csrf),
    _reset_guard: None = Depends(track_season_mutation),
    db: Session = Depends(get_db),
) -> dict:
    user = require_user(db, user_id, lock=True)
    card = db.get(Card, card_id)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "카드를 찾을 수 없습니다.")
    inventory = db.scalar(select(Inventory).where(Inventory.user_id == user_id, Inventory.card_id == card_id).with_for_update())
    before = inventory.quantity if inventory else 0
    reserved = inventory.reserved_quantity if inventory else 0
    if body.quantity < reserved:
        raise HTTPException(status.HTTP_409_CONFLICT, f"거래에 예약된 {reserved}장보다 적게 설정할 수 없습니다.")
    if inventory is None:
        inventory = Inventory(user_id=user_id, card_id=card_id, quantity=0)
        db.add(inventory)
    inventory.quantity = body.quantity
    if body.quantity > before:
        unlock_card(db, user_id, card_id)
    db.add(AdminAudit(admin_id=admin.id, action="inventory.set", target_type="user", target_id=str(user_id), details_json=json.dumps({"card_id": card_id, "before": before, "after": body.quantity})))
    db.commit()
    return collection_state(db, user)


class UnlockBody(BaseModel):
    unlocked: bool


@router.put("/{user_id}/catalog/{card_id}")
def set_catalog_unlock(
    user_id: int,
    card_id: str,
    body: UnlockBody,
    admin: User = Depends(require_admin_csrf),
    _reset_guard: None = Depends(track_season_mutation),
    db: Session = Depends(get_db),
) -> dict:
    user = require_user(db, user_id, lock=True)
    if db.get(Card, card_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "카드를 찾을 수 없습니다.")
    existing = db.get(CatalogUnlock, (user_id, card_id))
    if body.unlocked and existing is None:
        unlock_card(db, user_id, card_id)
    elif not body.unlocked and existing is not None:
        db.delete(existing)
    db.add(AdminAudit(admin_id=admin.id, action="catalog.set", target_type="user", target_id=str(user_id), details_json=json.dumps({"card_id": card_id, "unlocked": body.unlocked})))
    db.commit()
    return collection_state(db, user)
