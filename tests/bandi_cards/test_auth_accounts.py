from datetime import timedelta

from bandi_cards.models import DrawSetting, DrawWallet, OAuthAttempt, User, WebSession, utcnow
from bandi_cards.security import SESSION_COOKIE, random_token, token_hash
from bandi_cards.services.discord_oauth import DiscordProfile
from bandi_cards.services.draws import draw_ticket_status


def test_first_login_warning_blocks_search_until_acknowledged(signed_in):
    client, _factory, _user_id, csrf = signed_in

    blocked = client.get("/api/users/search", params={"q": "bandi"})
    assert blocked.status_code == 428

    missing_csrf = client.post("/api/me/warning")
    assert missing_csrf.status_code == 403

    acknowledged = client.post("/api/me/warning", headers={"X-CSRF-Token": csrf})
    assert acknowledged.status_code == 204
    assert client.get("/api/users/search", params={"q": "bandi"}).status_code == 200


def test_duplicate_names_return_distinguishable_search_results(signed_in):
    client, factory, user_id, csrf = signed_in
    client.post("/api/me/warning", headers={"X-CSRF-Token": csrf})
    with factory() as db:
        db.add_all(
            [
                User(discord_id="202020", username="same", global_name="반디"),
                User(discord_id="303030", username="same", global_name="반디"),
            ]
        )
        db.commit()

    response = client.get("/api/users/search", params={"q": "same"})
    assert response.status_code == 200
    payload = response.json()
    assert [item["discord_id"] for item in payload] == ["202020", "303030"]
    assert all(item["avatar_url"] for item in payload)


def test_incoming_settings_default_on_and_change_independently(signed_in):
    client, _factory, _user_id, csrf = signed_in
    me = client.get("/api/auth/me").json()
    assert me["accepts_gifts"] is True
    assert me["accepts_trades"] is True
    client.post("/api/me/warning", headers={"X-CSRF-Token": csrf})

    changed = client.put(
        "/api/me/settings",
        headers={"X-CSRF-Token": csrf},
        json={"accepts_gifts": False, "accepts_trades": True},
    )
    assert changed.status_code == 200
    assert changed.json()["accepts_gifts"] is False
    assert changed.json()["accepts_trades"] is True


def test_expired_session_is_rejected(web_client, web_db):
    raw = random_token()
    with web_db() as db:
        user = User(discord_id="404040", username="old")
        db.add(user)
        db.flush()
        db.add(
            WebSession(
                token_hash=token_hash(raw),
                user_id=user.id,
                expires_at=utcnow() - timedelta(seconds=1),
            )
        )
        db.commit()
    web_client.cookies.set(SESSION_COOKIE, raw)
    assert web_client.get("/api/auth/me").status_code == 401


def test_csrf_token_is_stable_across_tabs_for_the_same_session(signed_in):
    client, _factory, _user_id, csrf = signed_in
    first = client.post("/api/auth/csrf").json()["csrf_token"]
    second = client.post("/api/auth/csrf").json()["csrf_token"]
    assert first == second == csrf
    assert client.post("/api/me/warning", headers={"X-CSRF-Token": first}).status_code == 204


def test_first_discord_login_gets_current_daily_allowance_and_one_time_bonus(web_client, web_db, monkeypatch):
    async def fake_exchange(_code, _verifier):
        return DiscordProfile(id="new-discord-user", username="newbie", global_name="신규 사용자", avatar=None)

    monkeypatch.setattr("bandi_cards.routes.auth.exchange_code", fake_exchange)
    with web_db() as db:
        setting = db.get(DrawSetting, 1)
        setting.daily_draws = 4
        setting.new_user_bonus_tickets = 6
        db.add(OAuthAttempt(state_hash=token_hash("first-state"), verifier="verifier", expires_at=utcnow() + timedelta(minutes=5)))
        db.commit()

    response = web_client.get(
        "/api/auth/discord/callback",
        params={"code": "code", "state": "first-state"},
        follow_redirects=False,
    )
    assert response.status_code == 307

    with web_db() as db:
        user = db.query(User).filter_by(discord_id="new-discord-user").one()
        status = draw_ticket_status(db, user.id)
        assert status["daily_remaining"] == 4
        assert status["bonus_tickets"] == 6
        assert status["draws_remaining"] == 10
        db.add(OAuthAttempt(state_hash=token_hash("second-state"), verifier="verifier", expires_at=utcnow() + timedelta(minutes=5)))
        db.commit()

    web_client.get(
        "/api/auth/discord/callback",
        params={"code": "code", "state": "second-state"},
        follow_redirects=False,
    )
    with web_db() as db:
        user = db.query(User).filter_by(discord_id="new-discord-user").one()
        assert db.get(DrawWallet, user.id).bonus_tickets == 6
