from __future__ import annotations

import json

from sqlalchemy.orm import Session

from ..models import NotificationOutbox


def enqueue_notification(db: Session, recipient_discord_id: str, kind: str, payload: dict) -> NotificationOutbox:
    item = NotificationOutbox(
        recipient_discord_id=recipient_discord_id,
        kind=kind,
        payload=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )
    db.add(item)
    return item
