from datetime import timedelta

import pytest

import firefly.discord_profiles as profiles
from bandi_cards.models import Card, Inventory, User, as_utc, utcnow
from bandi_cards.services.season_reset import execute_season_reset


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


@pytest.mark.asyncio
async def test_profile_sync_after_season_reset_preserves_user_identity(web_db, monkeypatch):
    monkeypatch.setattr(profiles, "SessionLocal", web_db)
    stale_attempt = utcnow() - timedelta(hours=7)
    with web_db() as db:
        user = User(
            discord_id="777",
            username="old",
            global_name="예전 이름",
            avatar_hash="old-avatar",
            profile_sync_attempted_at=stale_attempt,
        )
        cards = [
            Card(
                name=f"프로필 보존 카드 {rarity}",
                rarity=rarity,
                yp=rarity * 10,
                image_key=f"cards/profile-{rarity}.webp",
            )
            for rarity in range(1, 6)
        ]
        db.add_all([user, *cards])
        db.flush()
        db.add(Inventory(user_id=user.id, card_id=cards[4].id, quantity=1))
        db.commit()
        user_id = user.id

    with web_db() as db:
        execute_season_reset(db, admin_id=user_id)
        db.commit()

    assert await profiles.sync_profile_batch(Client()) == 1

    with web_db() as db:
        updated = db.get(User, user_id)
        assert updated is not None
        assert updated.id == user_id
        assert updated.discord_id == "777"
        assert updated.username == "new_username"
        assert updated.global_name == "새 표시 이름"
        assert updated.avatar_hash == "new-avatar"
        assert updated.profile_sync_error is None
        assert as_utc(updated.profile_synced_at) > stale_attempt
        assert as_utc(updated.profile_sync_attempted_at) > stale_attempt
