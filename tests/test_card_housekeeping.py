from datetime import timedelta

import firefly.card_housekeeping as housekeeping
from bandi_cards.models import NotificationOutbox, OAuthAttempt, User, WebSession, WebSocketTicket, utcnow


def test_housekeeping_only_deletes_expired_transient_records(web_db, monkeypatch):
    now = utcnow()
    with web_db() as db:
        user = User(discord_id="cleanup-user", username="cleanup")
        db.add(user)
        db.flush()
        db.add_all(
            [
                OAuthAttempt(state_hash="old", verifier="v", expires_at=now - timedelta(seconds=1)),
                OAuthAttempt(state_hash="fresh", verifier="v", expires_at=now + timedelta(hours=1)),
                WebSocketTicket(token_hash="old", user_id=user.id, expires_at=now - timedelta(seconds=1)),
                WebSocketTicket(token_hash="fresh", user_id=user.id, expires_at=now + timedelta(hours=1)),
                WebSession(
                    token_hash="idle",
                    user_id=user.id,
                    last_seen_at=now - timedelta(days=31),
                    expires_at=now + timedelta(days=10),
                ),
                NotificationOutbox(
                    recipient_discord_id=user.discord_id,
                    kind="gift_received",
                    payload="{}",
                    status="delivered",
                    created_at=now - timedelta(days=31),
                ),
                NotificationOutbox(
                    recipient_discord_id=user.discord_id,
                    kind="gift_received",
                    payload="{}",
                    status="pending",
                    created_at=now - timedelta(days=31),
                ),
            ]
        )
        db.commit()

    monkeypatch.setattr(housekeeping, "SessionLocal", web_db)
    assert housekeeping.clean_expired_card_site_records() == 4

    with web_db() as db:
        assert db.get(OAuthAttempt, "old") is None
        assert db.get(OAuthAttempt, "fresh") is not None
        assert db.get(WebSocketTicket, "old") is None
        assert db.get(WebSocketTicket, "fresh") is not None
        assert db.get(WebSession, "idle") is None
        assert db.query(NotificationOutbox).count() == 1
