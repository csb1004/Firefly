from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Card, CatalogUnlock, DiscardEvent, Inventory, User
from .set_effects import effective_yp


def unlock_card(db: Session, user_id: int, card_id: str) -> CatalogUnlock:
    unlocked = db.get(CatalogUnlock, (user_id, card_id))
    if unlocked is None:
        unlocked = CatalogUnlock(user_id=user_id, card_id=card_id)
        db.add(unlocked)
    return unlocked


@dataclass(frozen=True)
class DiscardPreview:
    card: Card
    quantity: int
    quantity_after: int
    yp_before: int
    yp_after: int


def preview_discard(db: Session, user_id: int, card_id: str, quantity: int) -> DiscardPreview:
    if quantity <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "수량은 1 이상이어야 합니다.")
    inventory = db.get(Inventory, (user_id, card_id))
    card = db.get(Card, card_id)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "카드를 찾을 수 없습니다.")
    if inventory is None or inventory.quantity - inventory.reserved_quantity < quantity:
        raise HTTPException(status.HTTP_409_CONFLICT, "거래 예약을 제외한 보유 수량이 부족합니다.")
    after = inventory.quantity - quantity
    before_yp = effective_yp(db, user_id).total_yp
    after_yp = effective_yp(db, user_id, quantity_overrides={card_id: after}).total_yp
    return DiscardPreview(card, quantity, after, before_yp, after_yp)


def discard_card(
    db: Session,
    user_id: int,
    card_id: str,
    quantity: int,
    idempotency_key: str,
) -> tuple[DiscardEvent, bool]:
    existing = db.scalar(
        select(DiscardEvent).where(
            DiscardEvent.user_id == user_id,
            DiscardEvent.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return existing, True
    db.scalar(select(User).where(User.id == user_id).with_for_update())
    existing = db.scalar(
        select(DiscardEvent).where(
            DiscardEvent.user_id == user_id,
            DiscardEvent.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return existing, True
    inventory = db.scalar(
        select(Inventory).where(Inventory.user_id == user_id, Inventory.card_id == card_id).with_for_update()
    )
    preview = preview_discard(db, user_id, card_id, quantity)
    if inventory is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "보유하지 않은 카드입니다.")
    inventory.quantity = preview.quantity_after
    event = DiscardEvent(
        user_id=user_id,
        card_id=card_id,
        card_name=preview.card.name,
        quantity=quantity,
        quantity_after=preview.quantity_after,
        yp_before=preview.yp_before,
        yp_after=preview.yp_after,
        idempotency_key=idempotency_key,
    )
    db.add(event)
    db.commit()
    return event, False
