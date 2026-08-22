import httpx
import pytest

from bandi_cards.services.discord_oauth import exchange_code


@pytest.mark.asyncio
async def test_exchange_code_returns_current_profile_without_retaining_token():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "temporary"})
        assert request.headers["Authorization"] == "Bearer temporary"
        return httpx.Response(
            200,
            json={"id": "999", "username": "new_name", "global_name": "새 이름", "avatar": "hash"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        profile = await exchange_code("code", "verifier", client)

    assert profile.id == "999"
    assert profile.username == "new_name"
    assert profile.global_name == "새 이름"
