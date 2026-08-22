from __future__ import annotations

import asyncio
from datetime import timedelta

import discord
from sqlalchemy import select

from bandi_cards.db import SessionLocal
from bandi_cards.models import User, utcnow


_profile_task: asyncio.Task | None = None
PROFILE_SYNC_INTERVAL = timedelta(hours=6)


def stale_profile_ids(limit: int = 50) -> list[str]:
    cutoff = utcnow() - PROFILE_SYNC_INTERVAL
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(User.discord_id)
                .where(User.profile_sync_attempted_at < cutoff)
                .order_by(User.profile_sync_attempted_at)
                .limit(limit)
            ).all()
        )


def save_profile(discord_id: str, discord_user=None, error: str | None = None) -> None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.discord_id == discord_id))
        if user is None:
            return
        now = utcnow()
        user.profile_sync_attempted_at = now
        if discord_user is not None:
            user.username = discord_user.name
            user.global_name = getattr(discord_user, "global_name", None)
            avatar = getattr(discord_user, "avatar", None)
            user.avatar_hash = getattr(avatar, "key", None) if avatar else None
            user.profile_synced_at = now
            user.profile_sync_error = None
        else:
            user.profile_sync_error = (error or "unknown error")[:300]
        db.commit()


async def sync_profile_batch(client: discord.Client, limit: int = 50) -> int:
    ids = await asyncio.to_thread(stale_profile_ids, limit)
    for discord_id in ids:
        try:
            profile = await client.fetch_user(int(discord_id))
        except (discord.HTTPException, OSError, ValueError) as exc:
            await asyncio.to_thread(save_profile, discord_id, error=str(exc))
        else:
            await asyncio.to_thread(save_profile, discord_id, profile)
    return len(ids)


async def _profile_loop(client: discord.Client) -> None:
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            processed = await sync_profile_batch(client)
        except Exception as exc:
            print("Discord profile sync error:", exc)
            processed = 0
        await asyncio.sleep(30 if processed else 300)


def start_profile_sync_task(client: discord.Client) -> None:
    global _profile_task
    if _profile_task and not _profile_task.done():
        return
    _profile_task = asyncio.create_task(_profile_loop(client))


def cancel_profile_sync_task() -> None:
    global _profile_task
    if _profile_task and not _profile_task.done():
        _profile_task.cancel()
    _profile_task = None
