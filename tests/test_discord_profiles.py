from datetime import timedelta

import pytest

import firefly.discord_profiles as profiles
from bandi_cards.models import User, utcnow


class Avatar:
    key = "new-avatar"


class DiscordUser:
    name = "new_username"
    global_name = "새 표시 이름"
    avatar = Avatar()


class Client:
    async def fetch_user(self, discord_id):
        assert discord_id == 777
        return DiscordUser()


@pytest.mark.asyncio
async def test_profile_sync_updates_username_display_name_and_avatar_without_guild(web_db, monkeypatch):
    monkeypatch.setattr(profiles, "SessionLocal", web_db)
    with web_db() as db:
        user = User(
            discord_id="777",
            username="old",
            global_name="예전 이름",
            profile_sync_attempted_at=utcnow() - timedelta(hours=7),
        )
        db.add(user)
        db.commit()
        user_id = user.id

    assert await profiles.sync_profile_batch(Client()) == 1

    with web_db() as db:
        updated = db.get(User, user_id)
        assert updated.username == "new_username"
        assert updated.global_name == "새 표시 이름"
        assert updated.avatar_hash == "new-avatar"
        assert updated.profile_sync_error is None
