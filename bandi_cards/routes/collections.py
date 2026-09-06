from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..season_reset import track_season_mutation
from ..security import require_csrf_user, require_ready_user
from ..services.inventory import discard_card, preview_discard


router = APIRouter(prefix="/api/collection", tags=["collection"])


class DiscardSelection(BaseModel):
    card_id: str
    quantity: int = Field(ge=1)


class DiscardBody(DiscardSelection):
    idempotency_key: str = Field(min_length=8, max_length=64)


def discard_payload(item, *, repeated: bool = False) -> dict:
    return {
        "card_id": item.card.id if hasattr(item, "card") else item.card_id,
        "card_name": item.card.name if hasattr(item, "card") else item.card_name,
        "quantity": item.quantity,
        "quantity_after": item.quantity_after,
        "yp_before": item.yp_before,
        "yp_after": item.yp_after,
        "yp_change": item.yp_after - item.yp_before,
        "repeated": repeated,
    }


@router.post("/discard/preview")
def discard_preview(
    body: DiscardSelection,
    user: User = Depends(require_ready_user),
    db: Session = Depends(get_db),
) -> dict:
    return discard_payload(preview_discard(db, user.id, body.card_id, body.quantity))


@router.post("/discard")
def discard(
    body: DiscardBody,
    user: User = Depends(require_csrf_user),
    _reset_guard: None = Depends(track_season_mutation),
    db: Session = Depends(get_db),
) -> dict:
    event, repeated = discard_card(db, user.id, body.card_id, body.quantity, body.idempotency_key)
    return discard_payload(event, repeated=repeated)
