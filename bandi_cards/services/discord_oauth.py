from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from ..config import settings


AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
TOKEN_URL = "https://discord.com/api/oauth2/token"
CURRENT_USER_URL = "https://discord.com/api/v10/users/@me"


@dataclass(frozen=True)
class DiscordProfile:
    id: str
    username: str
    global_name: str | None
    avatar: str | None


def authorization_url(state: str, challenge: str) -> str:
    query = urlencode(
        {
            "client_id": settings.discord_client_id,
            "response_type": "code",
            "redirect_uri": settings.discord_redirect_uri,
            "scope": "identify",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


async def exchange_code(code: str, verifier: str, client: httpx.AsyncClient | None = None) -> DiscordProfile:
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        token_response = await client.post(
            TOKEN_URL,
            data={
                "client_id": settings.discord_client_id,
                "client_secret": settings.discord_client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.discord_redirect_uri,
                "code_verifier": verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]
        profile_response = await client.get(
            CURRENT_USER_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        profile_response.raise_for_status()
        payload = profile_response.json()
        return DiscordProfile(
            id=str(payload["id"]),
            username=payload["username"],
            global_name=payload.get("global_name"),
            avatar=payload.get("avatar"),
        )
    finally:
        if owns_client:
            await client.aclose()


def avatar_url(discord_id: str, avatar_hash: str | None) -> str:
    if avatar_hash:
        extension = "gif" if avatar_hash.startswith("a_") else "webp"
        return f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar_hash}.{extension}?size=128"
    try:
        index = (int(discord_id) >> 22) % 6
    except ValueError:
        index = 0
    return f"https://cdn.discordapp.com/embed/avatars/{index}.png"
