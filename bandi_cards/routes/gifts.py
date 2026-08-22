from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..security import require_csrf_user, require_ready_user
from ..services.card_assets import asset_store
from ..services.gifts import preview_gift, send_gift


router = APIRouter(prefix="/api/gifts", tags=["gifts"])


class GiftSelection(BaseModel):
    receiver_id: int
    card_id: str
    quantity: int = Field(ge=1)


class GiftBody(GiftSelection):
    idempotency_key: str = Field(min_length=8, max_length=64)


def preview_payload(preview) -> dict:
    return {
        "card": {
            "id": preview.card.id,
            "name": preview.card.name,
            "rarity": preview.card.rarity,
            "yp": preview.card.yp,
            "image_url": asset_store.url(preview.card.image_key),
        },
        "quantity": preview.quantity,
        "sender_yp_change": preview.sender_yp_change,
        "receiver_yp_change": preview.receiver_yp_change,
    }


@router.post("/preview")
def gift_preview(
    body: GiftSelection,
    sender: User = Depends(require_ready_user),
    db: Session = Depends(get_db),
) -> dict:
    return preview_payload(preview_gift(db, sender.id, body.receiver_id, body.card_id, body.quantity))


@router.post("")
def gift_send(
    body: GiftBody,
    sender: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
) -> dict:
    gift, preview, repeated = send_gift(
        db,
        sender.id,
        body.receiver_id,
        body.card_id,
        body.quantity,
        body.idempotency_key,
    )
    return {"gift_id": gift.id, "repeated": repeated, **preview_payload(preview)}
