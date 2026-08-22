from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy import select

from bandi_cards.db import SessionLocal
from bandi_cards.models import ImageCleanup, utcnow
from bandi_cards.services.card_assets import asset_store


_cleanup_task: asyncio.Task | None = None


def process_image_cleanup_batch(limit: int = 20) -> int:
    """Delete superseded card images after their database transaction commits."""
    with SessionLocal() as db:
        rows = db.scalars(
            select(ImageCleanup)
            .where(ImageCleanup.available_at <= utcnow())
            .order_by(ImageCleanup.available_at)
            .with_for_update(skip_locked=True)
            .limit(limit)
        ).all()
        processed = 0
        for row in rows:
            try:
                asset_store.delete(row.image_key)
            except Exception as exc:
                row.attempts += 1
                row.last_error = str(exc)[:500]
                row.available_at = utcnow() + timedelta(seconds=min(3600, 15 * (2 ** row.attempts)))
            else:
                db.delete(row)
                processed += 1
        db.commit()
        return processed


async def _cleanup_loop(client) -> None:
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            processed = await asyncio.to_thread(process_image_cleanup_batch)
        except Exception as exc:
            print("Card image cleanup error:", exc)
            processed = 0
        await asyncio.sleep(10 if processed else 300)


def start_image_cleanup_task(client) -> None:
    global _cleanup_task
    if _cleanup_task and not _cleanup_task.done():
        return
    _cleanup_task = asyncio.create_task(_cleanup_loop(client))


def cancel_image_cleanup_task() -> None:
    global _cleanup_task
    if _cleanup_task and not _cleanup_task.done():
        _cleanup_task.cancel()
    _cleanup_task = None
