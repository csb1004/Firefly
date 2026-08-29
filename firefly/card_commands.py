from __future__ import annotations

import discord
from sqlalchemy import select

from bandi_cards.db import SessionLocal
from bandi_cards.models import User
from bandi_cards.services.set_effects import effective_yp_many

from .config import CARD_SITE_URL


DEFAULT_CARD_SITE_URL = "https://younghogatcha.up.railway.app"


def _site_url(path: str = "") -> str:
    base = CARD_SITE_URL or DEFAULT_CARD_SITE_URL
    return f"{base}{path}"


def create_gacha_embed() -> discord.Embed:
    site_url = _site_url()
    return discord.Embed(
        title="영호 가챠",
        url=site_url,
        description=f"카드 뽑기, 도감, 거래는 영호 가챠에서 이용할 수 있어!\n{site_url}",
        color=0xFFD166,
    )


def create_ranking_embed(
    requester_discord_id: str,
    *,
    session_factory=SessionLocal,
    limit: int = 10,
) -> discord.Embed:
    with session_factory() as db:
        users = db.scalars(select(User).order_by(User.discord_id)).all()
        totals = effective_yp_many(db, [user.id for user in users])
        ranked = sorted(users, key=lambda user: (-totals[user.id].total_yp, user.discord_id))

        lines = [
            f"{rank}. {user.global_name or user.username} (@{user.username}) — {totals[user.id].total_yp:,} YP"
            for rank, user in enumerate(ranked[:limit], start=1)
        ]
        requester_rank = next(
            (
                (rank, totals[user.id].total_yp)
                for rank, user in enumerate(ranked, start=1)
                if user.discord_id == str(requester_discord_id)
            ),
            None,
        )

    ranking_url = _site_url("/ranking")
    description = "\n".join(lines) if lines else f"아직 랭킹에 등록된 사용자가 없어.\n{_site_url()}"
    embed = discord.Embed(
        title="영호 가챠 YP 랭킹",
        url=ranking_url,
        description=description,
        color=0xFFD166,
    )
    if requester_rank is None:
        embed.add_field(
            name="내 순위",
            value="아직 가입하지 않았어. 영호 가챠에 로그인해줘!",
            inline=False,
        )
    else:
        rank, total_yp = requester_rank
        embed.add_field(name="내 순위", value=f"{rank}위 · {total_yp:,} YP", inline=False)
    embed.add_field(name="전체 랭킹", value=ranking_url, inline=False)
    embed.set_footer(text="제목을 누르면 전체 랭킹을 볼 수 있어.")
    return embed
