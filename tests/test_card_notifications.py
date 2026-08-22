import json

import pytest

import firefly.card_notifications as notifications
from bandi_cards.models import NotificationOutbox, User


class FakeDiscordUser:
    def __init__(self, *, error=None):
        self.messages = []
        self.error = error

    async def send(self, message):
        if self.error:
            raise self.error
        self.messages.append(message)


class FakeClient:
    def __init__(self, user):
        self.user = user

    async def fetch_user(self, _discord_id):
        return self.user


def add_outbox(factory):
    with factory() as db:
        item = NotificationOutbox(
            recipient_discord_id="123",
            kind="gift_received",
            payload=json.dumps({"sender": "반디", "card_name": "금 카드", "quantity": 1, "path": "/profile/1"}),
        )
        db.add(item)
        db.commit()
        return item.id


def test_claim_batch_claims_each_row_once(web_db):
    item_id = add_outbox(web_db)
    with web_db() as db:
        assert notifications.claim_notification_batch(db) == [item_id]
    with web_db() as db:
        assert notifications.claim_notification_batch(db) == []


@pytest.mark.asyncio
async def test_delivered_dm_marks_outbox_without_touching_domain_state(web_db, monkeypatch):
    monkeypatch.setattr(notifications, "SessionLocal", web_db)
    item_id = add_outbox(web_db)
    with web_db() as db:
        notifications.claim_notification_batch(db)
    discord_user = FakeDiscordUser()

    await notifications.deliver_notification(FakeClient(discord_user), item_id)

    assert "금 카드" in discord_user.messages[0]
    with web_db() as db:
        item = db.get(NotificationOutbox, item_id)
        assert item.status == "delivered"
        assert item.delivered_at is not None


@pytest.mark.asyncio
async def test_temporary_dm_failure_is_retried(web_db, monkeypatch):
    monkeypatch.setattr(notifications, "SessionLocal", web_db)
    item_id = add_outbox(web_db)
    with web_db() as db:
        notifications.claim_notification_batch(db)

    await notifications.deliver_notification(FakeClient(FakeDiscordUser(error=OSError("network"))), item_id)

    with web_db() as db:
        item = db.get(NotificationOutbox, item_id)
        assert item.status == "retry"
        assert "network" in item.last_error
