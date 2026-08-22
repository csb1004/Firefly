from __future__ import annotations

from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Card, Inventory, TradeOffer, TradeRequest, TradeRoom, User, utcnow
from .notifications import enqueue_notification


ACTIVE_STATUSES = {"invited", "negotiating", "reconnecting"}


def participants(room: TradeRoom) -> list[int]:
    return [room.inviter_id, room.invitee_id]


def require_participant(room: TradeRoom | None, user_id: int) -> TradeRoom:
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "거래방을 찾을 수 없습니다.")
    if user_id not in participants(room):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "거래 참여자만 접근할 수 있습니다.")
    return room


def create_trade(db: Session, inviter_id: int, invitee_id: int) -> TradeRoom:
    if inviter_id == invitee_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "자기 자신과 거래할 수 없습니다.")
    invitee = db.get(User, invitee_id)
    if invitee is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "사용자를 찾을 수 없습니다.")
    if not invitee.accepts_trades:
        raise HTTPException(status.HTTP_409_CONFLICT, "상대방이 거래 초대를 꺼두었습니다.")
    existing = db.scalar(
        select(TradeRoom).where(
            TradeRoom.status.in_(ACTIVE_STATUSES),
            ((TradeRoom.inviter_id == inviter_id) & (TradeRoom.invitee_id == invitee_id))
            | ((TradeRoom.inviter_id == invitee_id) & (TradeRoom.invitee_id == inviter_id)),
        )
    )
    if existing:
        return existing
    room = TradeRoom(inviter_id=inviter_id, invitee_id=invitee_id)
    db.add(room)
    db.flush()
    inviter = db.get(User, inviter_id)
    enqueue_notification(
        db,
        invitee.discord_id,
        "trade_invite",
        {"room_id": room.id, "inviter": inviter.username, "path": f"/trade/{room.id}"},
    )
    db.commit()
    return room


def accept_invite(db: Session, room_id: str, user_id: int) -> TradeRoom:
    room = require_participant(db.scalar(select(TradeRoom).where(TradeRoom.id == room_id).with_for_update()), user_id)
    if room.invitee_id != user_id or room.status != "invited":
        raise HTTPException(status.HTTP_409_CONFLICT, "수락할 수 있는 초대 상태가 아닙니다.")
    room.status = "negotiating"
    db.commit()
    return room


def _release_room_reservations(db: Session, room_id: str) -> None:
    offers = db.scalars(
        select(TradeOffer).where(TradeOffer.room_id == room_id).order_by(TradeOffer.user_id, TradeOffer.card_id)
    ).all()
    for offer in offers:
        inventory = db.scalar(
            select(Inventory).where(
                Inventory.user_id == offer.user_id,
                Inventory.card_id == offer.card_id,
            ).with_for_update()
        )
        if inventory:
            inventory.reserved_quantity = max(0, inventory.reserved_quantity - offer.quantity)


def cancel_trade(db: Session, room_id: str, user_id: int | None = None) -> TradeRoom:
    room = db.scalar(select(TradeRoom).where(TradeRoom.id == room_id).with_for_update())
    if user_id is not None:
        require_participant(room, user_id)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "거래방을 찾을 수 없습니다.")
    if room.status in {"completed", "cancelled"}:
        return room
    _release_room_reservations(db, room.id)
    room.status = "cancelled"
    room.reconnect_deadline = None
    db.commit()
    return room


def set_offer(db: Session, room_id: str, user_id: int, card_id: str, quantity: int) -> TradeRoom:
    room = require_participant(db.scalar(select(TradeRoom).where(TradeRoom.id == room_id).with_for_update()), user_id)
    if room.status not in {"negotiating", "reconnecting"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "제안을 변경할 수 있는 거래 상태가 아닙니다.")
    if quantity < 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "수량은 0 이상이어야 합니다.")
    inventory = db.scalar(
        select(Inventory).where(Inventory.user_id == user_id, Inventory.card_id == card_id).with_for_update()
    )
    if inventory is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "보유하지 않은 카드입니다.")
    offer = db.get(TradeOffer, (room_id, user_id, card_id))
    previous = offer.quantity if offer else 0
    difference = quantity - previous
    if difference > inventory.quantity - inventory.reserved_quantity:
        raise HTTPException(status.HTTP_409_CONFLICT, "다른 거래나 선물을 제외한 수량이 부족합니다.")
    inventory.reserved_quantity += difference
    if quantity == 0:
        if offer:
            db.delete(offer)
    elif offer:
        offer.quantity = quantity
    else:
        db.add(TradeOffer(room_id=room_id, user_id=user_id, card_id=card_id, quantity=quantity))
    room.offer_version += 1
    room.inviter_accepted_version = None
    room.invitee_accepted_version = None
    db.commit()
    return room


def add_request(
    db: Session,
    room_id: str,
    requester_id: int,
    *,
    card_id: str | None,
    quantity: int | None,
    message: str | None,
) -> TradeRequest:
    room = require_participant(db.get(TradeRoom, room_id), requester_id)
    if room.status not in {"negotiating", "reconnecting"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "요청을 보낼 수 없는 거래 상태입니다.")
    target_id = room.invitee_id if requester_id == room.inviter_id else room.inviter_id
    if card_id is not None and db.get(Card, card_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "카드를 찾을 수 없습니다.")
    request = TradeRequest(
        room_id=room_id,
        requester_id=requester_id,
        target_id=target_id,
        kind="specific" if card_id else "more",
        card_id=card_id,
        quantity=quantity,
        message=(message or "")[:200] or None,
    )
    db.add(request)
    db.commit()
    return request


def accept_offer(db: Session, room_id: str, user_id: int) -> tuple[TradeRoom, bool]:
    room = require_participant(db.scalar(select(TradeRoom).where(TradeRoom.id == room_id).with_for_update()), user_id)
    if room.status != "negotiating":
        raise HTTPException(status.HTTP_409_CONFLICT, "현재 거래를 수락할 수 없습니다.")
    offers = db.scalars(select(TradeOffer).where(TradeOffer.room_id == room_id)).all()
    if not any(offer.user_id == room.inviter_id for offer in offers) or not any(offer.user_id == room.invitee_id for offer in offers):
        raise HTTPException(status.HTTP_409_CONFLICT, "양쪽 모두 한 장 이상 제안해야 합니다.")
    if user_id == room.inviter_id:
        room.inviter_accepted_version = room.offer_version
    else:
        room.invitee_accepted_version = room.offer_version
    completed = (
        room.inviter_accepted_version == room.offer_version
        and room.invitee_accepted_version == room.offer_version
    )
    if completed:
        ordered_offers = sorted(offers, key=lambda offer: (offer.user_id, offer.card_id))
        inventories = {}
        for offer in ordered_offers:
            inventory = db.scalar(
                select(Inventory).where(
                    Inventory.user_id == offer.user_id,
                    Inventory.card_id == offer.card_id,
                ).with_for_update()
            )
            if inventory is None or inventory.quantity < offer.quantity or inventory.reserved_quantity < offer.quantity:
                room.inviter_accepted_version = None
                room.invitee_accepted_version = None
                db.commit()
                raise HTTPException(status.HTTP_409_CONFLICT, "예약된 카드 수량이 변경되어 다시 확인해야 합니다.")
            inventories[(offer.user_id, offer.card_id)] = inventory
        for offer in ordered_offers:
            source = inventories[(offer.user_id, offer.card_id)]
            target_id = room.invitee_id if offer.user_id == room.inviter_id else room.inviter_id
            target = db.scalar(
                select(Inventory).where(Inventory.user_id == target_id, Inventory.card_id == offer.card_id).with_for_update()
            )
            if target is None:
                target = Inventory(user_id=target_id, card_id=offer.card_id, quantity=0)
                db.add(target)
            source.quantity -= offer.quantity
            source.reserved_quantity -= offer.quantity
            target.quantity += offer.quantity
        room.status = "completed"
        for recipient_id in participants(room):
            recipient = db.get(User, recipient_id)
            enqueue_notification(
                db,
                recipient.discord_id,
                "trade_completed",
                {"room_id": room.id, "path": f"/trade/{room.id}"},
            )
    db.commit()
    return room, completed


def room_payload(db: Session, room: TradeRoom) -> dict:
    offers = db.execute(
        select(TradeOffer, Card)
        .join(Card, Card.id == TradeOffer.card_id)
        .where(TradeOffer.room_id == room.id)
        .order_by(TradeOffer.user_id, Card.rarity.desc(), Card.name)
    ).all()
    requests = db.scalars(
        select(TradeRequest).where(TradeRequest.room_id == room.id).order_by(TradeRequest.created_at.desc()).limit(20)
    ).all()
    return {
        "id": room.id,
        "status": room.status,
        "inviter_id": room.inviter_id,
        "invitee_id": room.invitee_id,
        "offer_version": room.offer_version,
        "accepted": {
            str(room.inviter_id): room.inviter_accepted_version == room.offer_version,
            str(room.invitee_id): room.invitee_accepted_version == room.offer_version,
        },
        "offers": [
            {"user_id": offer.user_id, "card_id": card.id, "card_name": card.name, "rarity": card.rarity, "quantity": offer.quantity}
            for offer, card in offers
        ],
        "requests": [
            {"id": item.id, "requester_id": item.requester_id, "target_id": item.target_id, "kind": item.kind, "card_id": item.card_id, "quantity": item.quantity, "message": item.message}
            for item in requests
        ],
        "reconnect_deadline": room.reconnect_deadline.isoformat() if room.reconnect_deadline else None,
    }


def mark_user_reconnecting(db: Session, user_id: int) -> list[str]:
    rooms = db.scalars(
        select(TradeRoom).where(
            TradeRoom.status == "negotiating",
            (TradeRoom.inviter_id == user_id) | (TradeRoom.invitee_id == user_id),
        )
    ).all()
    deadline = utcnow() + timedelta(seconds=15)
    for room in rooms:
        room.status = "reconnecting"
        room.reconnect_deadline = deadline
    db.commit()
    return [room.id for room in rooms]


def restore_user_rooms(db: Session, user_id: int, is_online=None) -> list[str]:
    rooms = db.scalars(
        select(TradeRoom).where(
            TradeRoom.status == "reconnecting",
            (TradeRoom.inviter_id == user_id) | (TradeRoom.invitee_id == user_id),
        )
    ).all()
    restored = []
    for room in rooms:
        if is_online and not all(is_online(participant_id) for participant_id in participants(room)):
            continue
        room.status = "negotiating"
        room.reconnect_deadline = None
        restored.append(room.id)
    db.commit()
    return restored


def cancel_user_rooms(db: Session, user_id: int) -> list[str]:
    room_ids = db.scalars(
        select(TradeRoom.id).where(
            TradeRoom.status == "reconnecting",
            (TradeRoom.inviter_id == user_id) | (TradeRoom.invitee_id == user_id),
        )
    ).all()
    for room_id in room_ids:
        cancel_trade(db, room_id)
    return list(room_ids)


def cancel_all_active_rooms(db: Session) -> int:
    room_ids = db.scalars(select(TradeRoom.id).where(TradeRoom.status.in_(ACTIVE_STATUSES))).all()
    for room_id in room_ids:
        cancel_trade(db, room_id)
    return len(room_ids)
