from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy import delete, or_

from bandi_cards.db import SessionLocal
from bandi_cards.models import NotificationOutbox, OAuthAttempt, WebSession, WebSocketTicket, utcnow


_housekeeping_task: asyncio.Task | None = None


def clean_expired_card_site_records() -> int:
    now = utcnow()
    idle_cutoff = now - timedelta(days=30)
    notification_cutoff = now - timedelta(days=30)
    with SessionLocal() as db:
        counts = [
            db.execute(delete(OAuthAttempt).where(OAuthAttempt.expires_at <= now)).rowcount or 0,
            db.execute(delete(WebSocketTicket).where(WebSocketTicket.expires_at <= now)).rowcount or 0,
            db.execute(
                delete(WebSession).where(
                    or_(WebSession.expires_at <= now, WebSession.last_seen_at <= idle_cutoff)
                )
            ).rowcount
            or 0,
            db.execute(
                delete(NotificationOutbox).where(
                    NotificationOutbox.status.in_(["delivered", "failed"]),
                    NotificationOutbox.created_at <= notification_cutoff,
                )
            ).rowcount
            or 0,
        ]
        db.commit()
        return sum(counts)


async def _housekeeping_loop(client) -> None:
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            await asyncio.to_thread(clean_expired_card_site_records)
        except Exception as exc:
            print("Card site housekeeping error:", exc)
        await asyncio.sleep(6 * 60 * 60)


def start_card_housekeeping_task(client) -> None:
    global _housekeeping_task
    if _housekeeping_task and not _housekeeping_task.done():
        return
    _housekeeping_task = asyncio.create_task(_housekeeping_loop(client))


def cancel_card_housekeeping_task() -> None:
    global _housekeeping_task
    if _housekeeping_task and not _housekeeping_task.done():
        _housekeeping_task.cancel()
    _housekeeping_task = None
