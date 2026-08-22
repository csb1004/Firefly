from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    AdminAudit,
    Card,
    ImageCleanup,
    Inventory,
    ProbabilityAudit,
    RaritySetting,
    TradeOffer,
    TradeRoom,
    User,
)
from ..security import require_admin, require_admin_csrf, require_ready_user
from ..services.card_assets import asset_store
from ..services.probabilities import base_probabilities, card_probabilities, validate_probability_configuration


router = APIRouter(prefix="/api", tags=["cards"])


def serialize_card(card: Card) -> dict:
    return {
        "id": card.id,
        "name": card.name,
        "rarity": card.rarity,
        "yp": card.yp,
        "weight": float(card.weight) if card.weight is not None else None,
        "active": card.active,
        "image_url": asset_store.url(card.image_key),
    }


@router.get("/cards")
def list_cards(_: User = Depends(require_ready_user), db: Session = Depends(get_db)) -> list[dict]:
    return [serialize_card(card) for card in db.scalars(select(Card).order_by(Card.rarity.desc(), Card.name)).all()]


@router.get("/cards/{card_id}")
def card_detail(card_id: str, _: User = Depends(require_ready_user), db: Session = Depends(get_db)) -> dict:
    card = db.get(Card, card_id)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "카드를 찾을 수 없습니다.")
    return serialize_card(card)


@router.get("/assets/{key:path}", include_in_schema=False)
def local_asset(key: str):
    path = asset_store.local_path(key)
    if path is None or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "이미지를 찾을 수 없습니다.")
    return FileResponse(path, media_type="image/webp")


@router.get("/probabilities")
def probabilities(_: User = Depends(require_ready_user), db: Session = Depends(get_db)) -> dict:
    return {"rarities": base_probabilities(db), "cards": card_probabilities(db)}


@router.get("/admin/cards")
def admin_cards(_: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[dict]:
    return [serialize_card(card) for card in db.scalars(select(Card).order_by(Card.rarity.desc(), Card.name)).all()]


@router.post("/admin/cards", status_code=201)
async def create_card(
    name: str = Form(min_length=1, max_length=100),
    rarity: int = Form(ge=1, le=5),
    yp: int = Form(ge=0),
    weight: float | None = Form(default=None, gt=0),
    active: bool = Form(default=True),
    crop_x: float | None = Form(default=None),
    crop_y: float | None = Form(default=None),
    crop_width: float | None = Form(default=None),
    crop_height: float | None = Form(default=None),
    image: UploadFile = File(),
    admin: User = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> dict:
    if db.scalar(select(Card).where(func.lower(Card.name) == name.strip().lower())):
        raise HTTPException(status.HTTP_409_CONFLICT, "같은 이름의 카드가 이미 있습니다.")
    image_key = await asset_store.save(image, crop_x, crop_y, crop_width, crop_height)
    card = Card(name=name.strip(), rarity=rarity, yp=yp, weight=weight, active=active, image_key=image_key)
    db.add(card)
    db.flush()
    db.add(AdminAudit(admin_id=admin.id, action="card.create", target_type="card", target_id=card.id, details_json=json.dumps(serialize_card(card), ensure_ascii=False)))
    db.commit()
    return serialize_card(card)


@router.put("/admin/cards/{card_id}")
async def update_card(
    card_id: str,
    name: str = Form(min_length=1, max_length=100),
    rarity: int = Form(ge=1, le=5),
    yp: int = Form(ge=0),
    weight: float | None = Form(default=None, gt=0),
    active: bool = Form(default=True),
    image: UploadFile | None = File(default=None),
    admin: User = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> dict:
    card = db.get(Card, card_id)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "카드를 찾을 수 없습니다.")
    normalized_name = name.strip()
    duplicate = db.scalar(
        select(Card.id).where(
            Card.id != card_id,
            func.lower(Card.name) == normalized_name.lower(),
        )
    )
    if duplicate:
        raise HTTPException(status.HTTP_409_CONFLICT, "같은 이름의 카드가 이미 있습니다.")
    if card.active and (not active or rarity != card.rarity):
        remaining = db.scalar(
            select(func.count(Card.id)).where(
                Card.id != card_id,
                Card.active.is_(True),
                Card.rarity == card.rarity,
            )
        )
        if base_probabilities(db).get(card.rarity, 0) > 0 and not remaining:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"확률이 설정된 {card.rarity}성의 마지막 활성 카드는 제외하거나 이동할 수 없습니다.",
            )
    before = serialize_card(card)
    old_key = card.image_key
    if image and image.filename:
        card.image_key = await asset_store.save(image)
    card.name = normalized_name
    card.rarity = rarity
    card.yp = yp
    card.weight = weight
    card.active = active
    db.add(AdminAudit(admin_id=admin.id, action="card.update", target_type="card", target_id=card.id, details_json=json.dumps({"before": before, "after": serialize_card(card)}, ensure_ascii=False)))
    if card.image_key != old_key:
        db.add(ImageCleanup(image_key=old_key))
    db.commit()
    return serialize_card(card)


class ProbabilityBody(BaseModel):
    probabilities: dict[int, float]


@router.put("/admin/probabilities")
def update_probabilities(
    body: ProbabilityBody,
    admin: User = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> dict:
    values = {int(key): float(value) for key, value in body.probabilities.items()}
    validate_probability_configuration(db, values)
    before = base_probabilities(db)
    for rarity, probability in values.items():
        db.get(RaritySetting, rarity).probability = probability
    db.add(ProbabilityAudit(admin_id=admin.id, before_json=json.dumps(before), after_json=json.dumps(values)))
    db.commit()
    return {"rarities": values, "cards": card_probabilities(db, values)}


@router.get("/admin/cards/{card_id}/delete-preview")
def delete_preview(card_id: str, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    card = db.get(Card, card_id)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "카드를 찾을 수 없습니다.")
    copies, players = db.execute(
        select(func.coalesce(func.sum(Inventory.quantity), 0), func.count(Inventory.user_id)).where(Inventory.card_id == card_id)
    ).one()
    rooms = db.scalar(
        select(func.count(func.distinct(TradeOffer.room_id))).join(TradeRoom, TradeRoom.id == TradeOffer.room_id).where(TradeOffer.card_id == card_id, TradeRoom.status.in_(["invited", "negotiating", "reconnecting"]))
    )
    return {"card": serialize_card(card), "affected_players": players, "total_copies": copies, "active_trade_rooms": rooms or 0}


class DeleteCardBody(BaseModel):
    confirm_name: str = Field(min_length=1)


@router.delete("/admin/cards/{card_id}", status_code=204)
def permanently_delete_card(
    card_id: str,
    body: DeleteCardBody,
    admin: User = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
):
    card = db.get(Card, card_id)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "카드를 찾을 수 없습니다.")
    if body.confirm_name != card.name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "카드 이름이 일치하지 않습니다.")
    room_ids = db.scalars(select(TradeOffer.room_id).where(TradeOffer.card_id == card_id)).all()
    if room_ids:
        offers = db.scalars(select(TradeOffer).where(TradeOffer.room_id.in_(room_ids))).all()
        for offer in offers:
            inventory = db.get(Inventory, (offer.user_id, offer.card_id))
            if inventory is not None:
                inventory.reserved_quantity = max(0, inventory.reserved_quantity - offer.quantity)
        db.execute(update(TradeRoom).where(TradeRoom.id.in_(room_ids), TradeRoom.status.notin_(["completed", "cancelled"])).values(status="cancelled"))
    db.add(AdminAudit(admin_id=admin.id, action="card.delete", target_type="card", target_id=card.id, details_json=json.dumps({"name": card.name}, ensure_ascii=False)))
    db.add(ImageCleanup(image_key=card.image_key))
    db.delete(card)
    db.commit()
