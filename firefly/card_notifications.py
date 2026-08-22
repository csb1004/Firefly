from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import discord
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from bandi_cards.db import SessionLocal
from bandi_cards.models import NotificationOutbox, utcnow
from .config import CARD_SITE_URL


_notification_task: asyncio.Task | None = None


def claim_notification_batch(db: Session, limit: int = 20) -> list[str]:
    now = utcnow()
    stale_claim = now - timedelta(minutes=5)
    rows = db.scalars(
        select(NotificationOutbox)
        .where(
            NotificationOutbox.available_at <= now,
            or_(
                NotificationOutbox.status.in_(["pending", "retry"]),
                (NotificationOutbox.status == "processing")
                & (NotificationOutbox.claimed_at < stale_claim),
            ),
        )
        .order_by(NotificationOutbox.available_at, NotificationOutbox.created_at)
        .with_for_update(skip_locked=True)
        .limit(limit)
    ).all()
    for row in rows:
        row.status = "processing"
        row.claimed_at = now
        row.attempts += 1
    db.commit()
    return [row.id for row in rows]


def notification_message(kind: str, payload: dict) -> str:
    path = payload.get("path", "/")
    url = f"{CARD_SITE_URL}{path}" if CARD_SITE_URL else path
    if kind == "gift_received":
        return f"{payload.get('sender', '누군가')}님에게서 {payload.get('card_name')} ×{payload.get('quantity')} 선물이 도착했어!\n{url}"
    if kind == "trade_invite":
        return f"{payload.get('inviter', '누군가')}님이 카드 거래에 초대했어.\n{url}"
    if kind == "trade_completed":
        return f"카드 거래가 완료됐어. 결과를 확인해봐!\n{url}"
    return f"반디 카드 알림이 도착했어.\n{url}"


def finish_notification(item_id: str, *, error: str | None = None, permanent: bool = False) -> None:
    with SessionLocal() as db:
        item = db.get(NotificationOutbox, item_id)
        if item is None:
            return
        if error is None:
            item.status = "delivered"
            item.delivered_at = utcnow()
            item.last_error = None
        elif permanent or item.attempts >= 6:
            item.status = "failed"
            item.last_error = error[:500]
        else:
            item.status = "retry"
            item.last_error = error[:500]
            item.available_at = utcnow() + timedelta(seconds=min(3600, 15 * (2 ** item.attempts)))
        db.commit()


async def deliver_notification(client: discord.Client, item_id: str) -> None:
    with SessionLocal() as db:
        item = db.get(NotificationOutbox, item_id)
        if item is None or item.status != "processing":
            return
        discord_id = int(item.recipient_discord_id)
        kind = item.kind
        payload = json.loads(item.payload)
    try:
        user = await client.fetch_user(discord_id)
        await user.send(notification_message(kind, payload))
    except (discord.Forbidden, discord.NotFound) as exc:
        await asyncio.to_thread(finish_notification, item_id, error=str(exc), permanent=True)
    except (discord.HTTPException, OSError) as exc:
        await asyncio.to_thread(finish_notification, item_id, error=str(exc))
    else:
        await asyncio.to_thread(finish_notification, item_id)


async def process_notification_batch(client: discord.Client) -> int:
    def claim():
        with SessionLocal() as db:
            return claim_notification_batch(db)

    item_ids = await asyncio.to_thread(claim)
    for item_id in item_ids:
        await deliver_notification(client, item_id)
    return len(item_ids)


async def _notification_loop(client: discord.Client) -> None:
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            processed = await process_notification_batch(client)
        except Exception as exc:
            print("Card notification loop error:", exc)
            processed = 0
        await asyncio.sleep(2 if processed else 10)


def start_card_notification_task(client: discord.Client) -> None:
    global _notification_task
    if _notification_task and not _notification_task.done():
        return
    _notification_task = asyncio.create_task(_notification_loop(client))


def cancel_card_notification_task() -> None:
    global _notification_task
    if _notification_task and not _notification_task.done():
        _notification_task.cancel()
    _notification_task = None
