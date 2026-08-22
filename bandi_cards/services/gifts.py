from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Card, Gift, Inventory, User
from .inventory import unlock_card
from .notifications import enqueue_notification
from .set_effects import effective_yp


@dataclass(frozen=True)
class GiftPreview:
    card: Card
    quantity: int
    sender_yp_change: int
    receiver_yp_change: int


def _validate_gift(
    db: Session,
    sender_id: int,
    receiver_id: int,
    card_id: str,
    quantity: int,
    *,
    lock: bool = False,
) -> tuple[User, Card, Inventory, Inventory | None]:
    if sender_id == receiver_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "자기 자신에게 선물할 수 없습니다.")
    if quantity <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "수량은 1 이상이어야 합니다.")
    user_query = select(User).where(User.id.in_(sorted([sender_id, receiver_id]))).order_by(User.id)
    if lock:
        user_query = user_query.with_for_update()
    users = {user.id: user for user in db.scalars(user_query).all()}
    sender = users.get(sender_id)
    receiver = users.get(receiver_id)
    if sender is None or receiver is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "사용자를 찾을 수 없습니다.")
    if not receiver.accepts_gifts:
        raise HTTPException(status.HTTP_409_CONFLICT, "상대방이 선물 받기를 꺼두었습니다.")
    card = db.get(Card, card_id)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "카드를 찾을 수 없습니다.")
    inventory_query = select(Inventory).where(
        Inventory.card_id == card_id,
        Inventory.user_id.in_(sorted([sender_id, receiver_id])),
    ).order_by(Inventory.user_id, Inventory.card_id)
    if lock:
        inventory_query = inventory_query.with_for_update()
    inventories = {item.user_id: item for item in db.scalars(inventory_query).all()}
    sender_inventory = inventories.get(sender_id)
    receiver_inventory = inventories.get(receiver_id)
    if sender_inventory is None or sender_inventory.quantity - sender_inventory.reserved_quantity < quantity:
        raise HTTPException(status.HTTP_409_CONFLICT, "거래 예약을 제외한 보유 수량이 부족합니다.")
    return receiver, card, sender_inventory, receiver_inventory


def preview_gift(db: Session, sender_id: int, receiver_id: int, card_id: str, quantity: int) -> GiftPreview:
    _receiver, card, sender_inventory, receiver_inventory = _validate_gift(
        db, sender_id, receiver_id, card_id, quantity
    )
    sender_before = effective_yp(db, sender_id).total_yp
    receiver_before = effective_yp(db, receiver_id).total_yp
    sender_after = effective_yp(db, sender_id, quantity_overrides={card_id: sender_inventory.quantity - quantity}).total_yp
    receiver_quantity = receiver_inventory.quantity if receiver_inventory else 0
    receiver_after = effective_yp(db, receiver_id, quantity_overrides={card_id: receiver_quantity + quantity}).total_yp
    return GiftPreview(
        card=card,
        quantity=quantity,
        sender_yp_change=sender_after - sender_before,
        receiver_yp_change=receiver_after - receiver_before,
    )


def send_gift(
    db: Session,
    sender_id: int,
    receiver_id: int,
    card_id: str,
    quantity: int,
    idempotency_key: str,
) -> tuple[Gift, GiftPreview, bool]:
    existing = db.scalar(
        select(Gift).where(Gift.sender_id == sender_id, Gift.idempotency_key == idempotency_key)
    )
    if existing:
        card = db.get(Card, existing.card_id) if existing.card_id else None
        if card is None:
            raise HTTPException(status.HTTP_410_GONE, "선물한 카드가 삭제되었습니다.")
        return existing, GiftPreview(
            card,
            existing.quantity,
            existing.sender_yp_change,
            existing.receiver_yp_change,
        ), True

    receiver, card, sender_inventory, receiver_inventory = _validate_gift(
        db, sender_id, receiver_id, card_id, quantity, lock=True
    )
    sender_before = effective_yp(db, sender_id).total_yp
    receiver_before = effective_yp(db, receiver_id).total_yp
    sender_after = effective_yp(db, sender_id, quantity_overrides={card_id: sender_inventory.quantity - quantity}).total_yp
    receiver_quantity = receiver_inventory.quantity if receiver_inventory else 0
    receiver_after = effective_yp(db, receiver_id, quantity_overrides={card_id: receiver_quantity + quantity}).total_yp
    preview = GiftPreview(card, quantity, sender_after - sender_before, receiver_after - receiver_before)
    sender_inventory.quantity -= quantity
    if receiver_inventory is None:
        receiver_inventory = Inventory(user_id=receiver_id, card_id=card_id, quantity=0)
        db.add(receiver_inventory)
    receiver_inventory.quantity += quantity
    unlock_card(db, receiver_id, card_id)
    gift = Gift(
        sender_id=sender_id,
        receiver_id=receiver_id,
        card_id=card_id,
        card_name=card.name,
        quantity=quantity,
        sender_yp_change=preview.sender_yp_change,
        receiver_yp_change=preview.receiver_yp_change,
        idempotency_key=idempotency_key,
    )
    db.add(gift)
    db.flush()
    sender = db.get(User, sender_id)
    enqueue_notification(
        db,
        receiver.discord_id,
        "gift_received",
        {
            "gift_id": gift.id,
            "sender": sender.username,
            "card_name": card.name,
            "quantity": quantity,
            "path": f"/profile/{receiver_id}",
        },
    )
    db.commit()
    return gift, preview, False
