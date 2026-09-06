import asyncio
import json
import threading
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from sqlalchemy import func, select

from bandi_cards.models import (
    AdminAudit,
    Card,
    CatalogUnlock,
    DrawHistory,
    DrawSetting,
    DrawState,
    DrawWallet,
    FiveStarEvent,
    Inventory,
    NotificationOutbox,
    OAuthAttempt,
    TradeRoom,
    User,
    utcnow,
)
from bandi_cards.security import token_hash
from bandi_cards.services.discord_oauth import DiscordProfile
from bandi_cards.services.draws import draw_ticket_status, logical_draw_day
from bandi_cards.services.gifts import send_gift
from bandi_cards.services.season_reset import CONFIRMATION_TEXT
from bandi_cards.services.trades import accept_invite, accept_offer, create_trade, set_offer


RESET_OPERATION_ID = "season-reset-api-test-0001"


GUARDED_ROUTES = {
    ("POST", "/api/auth/websocket-ticket"),
    ("PUT", "/api/admin/draw-settings"),
    ("POST", "/api/admin/users/{user_id}/draw-tickets/grant"),
    ("POST", "/api/admin/users/{user_id}/draw-tickets/reset-today"),
    ("PUT", "/api/admin/users/{user_id}/inventory/{card_id}"),
    ("PUT", "/api/admin/users/{user_id}/catalog/{card_id}"),
    ("POST", "/api/admin/sets"),
    ("PUT", "/api/admin/sets/{set_id}"),
    ("DELETE", "/api/admin/sets/{set_id}"),
    ("POST", "/api/admin/cards"),
    ("PUT", "/api/admin/cards/{card_id}"),
    ("PUT", "/api/admin/probabilities"),
    ("DELETE", "/api/admin/cards/{card_id}"),
    ("POST", "/api/collection/discard"),
    ("POST", "/api/draw"),
    ("POST", "/api/draw/ten"),
    ("POST", "/api/gifts"),
    ("POST", "/api/trades/invite"),
    ("POST", "/api/trades/{room_id}/accept-invite"),
    ("PUT", "/api/trades/{room_id}/offer"),
    ("POST", "/api/trades/{room_id}/request"),
    ("POST", "/api/trades/{room_id}/accept"),
    ("POST", "/api/trades/{room_id}/cancel"),
}

UNGUARDED_MUTATING_ROUTES = {
    ("POST", "/api/auth/csrf"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/me/warning"),
    ("PUT", "/api/me/settings"),
    ("POST", "/api/collection/discard/preview"),
    ("POST", "/api/gifts/preview"),
    ("POST", "/api/admin/season-reset"),
}


@contextmanager
def _held_reset(coordinator):
    entered = threading.Event()
    release = threading.Event()
    errors = []

    def hold() -> None:
        async def scenario() -> None:
            async with coordinator.reset():
                entered.set()
                await asyncio.to_thread(release.wait)

        try:
            asyncio.run(scenario())
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=hold)
    thread.start()
    assert entered.wait(timeout=2)
    try:
        yield
    finally:
        release.set()
        thread.join(timeout=2)
    assert thread.is_alive() is False
    assert errors == []


def _seed_api_season(factory, admin_id: int, *, daily_draws: int = 3, bonus_tickets: int = 7) -> int:
    with factory() as db:
        setting = db.get(DrawSetting, 1)
        setting.daily_draws = daily_draws
        setting.new_user_bonus_tickets = bonus_tickets
        player = User(
            discord_id="reset-api-player",
            username="reset_player",
            global_name="초기화 플레이어",
            warning_acknowledged=True,
            accepts_gifts=False,
            accepts_trades=False,
        )
        cards = [
            Card(
                name=f"초기화 API {rarity}성",
                rarity=rarity,
                yp=rarity * 100,
                image_key=f"cards/reset-api-{rarity}.webp",
            )
            for rarity in range(1, 6)
        ]
        db.add_all([player, *cards])
        db.flush()
        db.add_all(
            [
                Inventory(user_id=admin_id, card_id=cards[4].id, quantity=3),
                CatalogUnlock(user_id=admin_id, card_id=cards[4].id),
                DrawWallet(user_id=admin_id, bonus_tickets=99),
                AdminAudit(
                    admin_id=admin_id,
                    action="old.admin.action",
                    target_type="card",
                    target_id=cards[4].id,
                    details_json='{"old":true}',
                ),
            ]
        )
        db.commit()
        return player.id


def test_non_admin_cannot_preview_or_execute_reset(signed_in):
    client, _factory, _user_id, csrf = signed_in
    client.post("/api/me/warning", headers={"X-CSRF-Token": csrf})

    assert client.get("/api/admin/season-reset/preview").status_code == 403
    assert client.post(
        "/api/admin/season-reset",
        headers={"X-CSRF-Token": csrf},
        json={"confirmation": CONFIRMATION_TEXT, "operation_id": RESET_OPERATION_ID},
    ).status_code == 403


def test_reset_requires_csrf_and_exact_confirmation_without_changing_data(admin_signed_in):
    client, factory, admin_id, csrf = admin_signed_in
    _seed_api_season(factory, admin_id)

    assert client.post(
        "/api/admin/season-reset",
        json={"confirmation": CONFIRMATION_TEXT, "operation_id": RESET_OPERATION_ID},
    ).status_code == 403
    missing_operation = client.post(
        "/api/admin/season-reset",
        headers={"X-CSRF-Token": csrf},
        json={"confirmation": CONFIRMATION_TEXT},
    )
    assert missing_operation.status_code == 422
    wrong = client.post(
        "/api/admin/season-reset",
        headers={"X-CSRF-Token": csrf},
        json={"confirmation": "시즌 초기화", "operation_id": RESET_OPERATION_ID},
    )
    assert wrong.status_code == 400
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Inventory)) == 1
        assert db.get(DrawWallet, admin_id).bonus_tickets == 99


def test_admin_preview_and_execute_preserve_session_and_settings(admin_signed_in):
    client, factory, admin_id, csrf = admin_signed_in
    player_id = _seed_api_season(factory, admin_id)

    preview = client.get("/api/admin/season-reset/preview")
    assert preview.status_code == 200
    assert preview.json()["delete_counts"]["inventory"] == 1
    assert preview.json()["preserved"] == {
        "users": 2,
        "cards": 5,
        "card_sets": 0,
        "rarity_settings": 5,
        "image_cleanup": 0,
        "draw_settings": {"daily_draws": 3, "new_user_bonus_tickets": 7},
    }

    reset = client.post(
        "/api/admin/season-reset",
        headers={"X-CSRF-Token": csrf},
        json={"confirmation": CONFIRMATION_TEXT, "operation_id": RESET_OPERATION_ID},
    )
    assert reset.status_code == 200
    payload = reset.json()
    assert payload["grant"] == {"granted_users": 2, "tickets_per_user": 7, "total_tickets": 14}
    assert client.get("/api/auth/me").status_code == 200

    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Inventory)) == 0
        assert db.scalar(select(func.count()).select_from(CatalogUnlock)) == 0
        assert db.scalar(select(func.count()).select_from(Card)) == 5
        assert db.get(DrawSetting, 1).daily_draws == 3
        assert db.get(DrawSetting, 1).new_user_bonus_tickets == 7
        assert db.get(DrawWallet, admin_id).bonus_tickets == 7
        assert db.get(DrawWallet, player_id).bonus_tickets == 7
        player = db.get(User, player_id)
        assert (player.username, player.accepts_gifts, player.accepts_trades) == (
            "reset_player",
            False,
            False,
        )
        audits = db.scalars(select(AdminAudit)).all()
        assert len(audits) == 1
        assert audits[0].id == payload["audit_id"]
        assert json.loads(audits[0].details_json)["grant"] == payload["grant"]


def test_api_retry_replays_committed_reset_without_touching_new_progress(
    admin_signed_in,
    monkeypatch,
):
    from bandi_cards.routes import admin_reset

    client, factory, admin_id, csrf = admin_signed_in
    _seed_api_season(factory, admin_id)
    recorder = BroadcastRecorder()
    monkeypatch.setattr(admin_reset, "manager", recorder, raising=False)
    request_body = {
        "confirmation": CONFIRMATION_TEXT,
        "operation_id": "season-reset-lost-response-0001",
    }

    first = client.post(
        "/api/admin/season-reset",
        headers={"X-CSRF-Token": csrf},
        json=request_body,
    )
    assert first.status_code == 200

    with factory() as db:
        card_id = db.scalar(select(Card.id).order_by(Card.id))
        db.add(Inventory(user_id=admin_id, card_id=card_id, quantity=1))
        db.commit()

    replay = client.post(
        "/api/admin/season-reset",
        headers={"X-CSRF-Token": csrf},
        json=request_body,
    )

    assert replay.status_code == 200
    assert replay.json() == {**first.json(), "replayed": True}
    assert recorder.messages == [
        {
            "type": "season.reset",
            "operation_id": "season-reset-lost-response-0001",
        }
    ]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Inventory)) == 1
        assert db.scalar(select(func.count()).select_from(AdminAudit)) == 1


def test_reset_restarts_player_progress_and_gameplay_remains_available(admin_signed_in):
    client, factory, admin_id, csrf = admin_signed_in
    player_id = _seed_api_season(factory, admin_id, daily_draws=10, bonus_tickets=20)
    with factory() as db:
        player = db.get(User, player_id)
        player.accepts_gifts = True
        player.accepts_trades = True
        five_star = db.scalar(select(Card).where(Card.rarity == 5))
        old_draw = DrawHistory(
            user_id=admin_id,
            card_id=five_star.id,
            card_name=five_star.name,
            card_rarity=five_star.rarity,
            card_yp=five_star.yp,
            draw_day=logical_draw_day(),
            ticket_source="daily",
            idempotency_key="before-season-reset",
        )
        db.add(old_draw)
        db.flush()
        db.add_all(
            [
                DrawState(user_id=admin_id, pulls_since_four_plus=6, pulls_since_five=73),
                FiveStarEvent(draw_id=old_draw.id, user_id=admin_id, card_id=five_star.id),
                TradeRoom(inviter_id=admin_id, invitee_id=player_id),
                NotificationOutbox(
                    recipient_discord_id=player.discord_id,
                    kind="before_reset_marker",
                    payload='{"old":true}',
                ),
            ]
        )
        db.commit()

    reset = client.post(
        "/api/admin/season-reset",
        headers={"X-CSRF-Token": csrf},
        json={"confirmation": CONFIRMATION_TEXT, "operation_id": RESET_OPERATION_ID},
    )

    assert reset.status_code == 200
    assert client.get("/api/auth/me").json()["id"] == admin_id
    assert client.get("/api/collection/me").json()["cards"] == []
    catalog = client.get("/api/catalog").json()
    assert (catalog["owned_count"], catalog["total_count"]) == (0, 5)
    history = client.get("/api/draw/history").json()
    assert history["total"] == 0
    assert history["summary"] == {"total_draws": 0, "four_remaining": 10, "five_remaining": 90}
    assert client.get("/api/feed/five-stars").json()["items"] == []
    assert [item["total_yp"] for item in client.get("/api/rankings").json()["items"]] == [0, 0]
    assert client.get("/api/draw/status").json() == {
        "eligible": True,
        "draws_remaining": 30,
        "daily_remaining": 10,
        "bonus_tickets": 20,
        "four_remaining": 10,
        "five_remaining": 90,
    }
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(TradeRoom)) == 0
        assert db.scalar(select(func.count()).select_from(NotificationOutbox)) == 0

    ten = client.post(
        "/api/draw/ten",
        headers={"X-CSRF-Token": csrf},
        json={"idempotency_key": "post-reset-ten"},
    )
    single = client.post(
        "/api/draw",
        headers={"X-CSRF-Token": csrf},
        json={"idempotency_key": "post-reset-single"},
    )

    assert ten.status_code == 200
    assert len(ten.json()["cards"]) == 10
    assert single.status_code == 200
    assert client.get("/api/draw/history").json()["total"] == 11

    with factory() as db:
        gift_inventory = db.scalars(
            select(Inventory)
            .where(Inventory.user_id == admin_id, Inventory.quantity >= 3)
            .order_by(Inventory.quantity.desc(), Inventory.card_id)
        ).first()
        assert gift_inventory is not None
        card_id = gift_inventory.card_id

        _gift, _preview, repeated = send_gift(
            db,
            admin_id,
            player_id,
            card_id,
            1,
            "post-reset-gift",
        )
        assert repeated is False

        room = create_trade(db, admin_id, player_id)
        accept_invite(db, room.id, player_id)
        set_offer(db, room.id, admin_id, card_id, 1)
        set_offer(db, room.id, player_id, card_id, 1)
        _room, first_completed = accept_offer(db, room.id, admin_id)
        completed_room, second_completed = accept_offer(db, room.id, player_id)

        assert first_completed is False
        assert second_completed is True
        assert completed_room.status == "completed"
        assert sorted(db.scalars(select(NotificationOutbox.kind)).all()) == [
            "gift_received",
            "trade_completed",
            "trade_completed",
            "trade_invite",
        ]


def test_new_discord_user_after_reset_gets_current_daily_and_signup_bonus(
    admin_signed_in,
    monkeypatch,
):
    client, factory, admin_id, csrf = admin_signed_in
    _seed_api_season(factory, admin_id, daily_draws=10, bonus_tickets=20)

    reset = client.post(
        "/api/admin/season-reset",
        headers={"X-CSRF-Token": csrf},
        json={"confirmation": CONFIRMATION_TEXT, "operation_id": RESET_OPERATION_ID},
    )
    assert reset.status_code == 200

    async def fake_exchange(_code, _verifier):
        return DiscordProfile(
            id="post-reset-new-user",
            username="newbie",
            global_name="신규 사용자",
            avatar=None,
        )

    monkeypatch.setattr("bandi_cards.routes.auth.exchange_code", fake_exchange)
    with factory() as db:
        db.add(
            OAuthAttempt(
                state_hash=token_hash("post-reset-state"),
                verifier="verifier",
                expires_at=utcnow() + timedelta(minutes=5),
            )
        )
        db.commit()

    callback = client.get(
        "/api/auth/discord/callback",
        params={"code": "code", "state": "post-reset-state"},
        follow_redirects=False,
    )

    assert callback.status_code == 307
    with factory() as db:
        newcomer = db.scalar(select(User).where(User.discord_id == "post-reset-new-user"))
        assert newcomer is not None
        assert draw_ticket_status(db, newcomer.id) == {
            "eligible": True,
            "draws_remaining": 30,
            "daily_remaining": 10,
            "bonus_tickets": 20,
        }


def test_invalid_preserved_configuration_returns_422_without_deleting(admin_signed_in):
    client, factory, admin_id, csrf = admin_signed_in
    with factory() as db:
        db.add(
            AdminAudit(
                admin_id=admin_id,
                action="must.remain",
                target_type="test",
                target_id=None,
                details_json="{}",
            )
        )
        db.commit()

    preview = client.get("/api/admin/season-reset/preview")
    assert preview.status_code == 422
    reset = client.post(
        "/api/admin/season-reset",
        headers={"X-CSRF-Token": csrf},
        json={"confirmation": CONFIRMATION_TEXT, "operation_id": RESET_OPERATION_ID},
    )
    assert reset.status_code == 422
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(AdminAudit)) == 1


def test_overlapping_reset_maps_to_conflict(monkeypatch):
    from bandi_cards.routes import admin_reset
    from bandi_cards.season_reset import SeasonResetCoordinator

    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        async def held_reset(_factory, _admin_id, _operation_id):
            entered.set()
            await release.wait()
            return {"completed": True, "replayed": False}

        monkeypatch.setattr(admin_reset, "_complete_reset_transaction", held_reset)
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    season_reset_coordinator=SeasonResetCoordinator(),
                    session_factory=object(),
                )
            )
        )
        admin = SimpleNamespace(id=123)
        first = asyncio.create_task(
            admin_reset.reset_season(
                admin_reset.SeasonResetBody(
                    confirmation=CONFIRMATION_TEXT,
                    operation_id=RESET_OPERATION_ID,
                ),
                request,
                admin,
            )
        )
        await entered.wait()

        with pytest.raises(HTTPException) as caught:
            await admin_reset.reset_season(
                admin_reset.SeasonResetBody(
                    confirmation=CONFIRMATION_TEXT,
                    operation_id=RESET_OPERATION_ID,
                ),
                request,
                admin,
            )
        assert caught.value.status_code == 409

        release.set()
        assert await first == {"completed": True, "replayed": False}

    asyncio.run(scenario())


def test_repeated_request_cancellation_waits_for_database_worker(monkeypatch):
    from bandi_cards.routes import admin_reset
    from bandi_cards.season_reset import SeasonResetCoordinator

    worker_entered = threading.Event()
    release_worker = threading.Event()

    def held_commit(_factory, _admin_id, _operation_id):
        worker_entered.set()
        release_worker.wait(timeout=5)
        return {"completed": True}

    monkeypatch.setattr(admin_reset, "_commit_reset", held_commit)

    async def scenario() -> None:
        coordinator = SeasonResetCoordinator()

        async def request() -> dict:
            async with coordinator.reset():
                return await admin_reset._complete_reset_transaction(
                    object(),
                    123,
                    RESET_OPERATION_ID,
                )

        task = asyncio.create_task(request())
        assert await asyncio.to_thread(worker_entered.wait, 2)
        assert coordinator.is_resetting is True
        try:
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert task.done() is False
            assert coordinator.is_resetting is True
        finally:
            release_worker.set()

        assert await task == {"completed": True}
        assert coordinator.is_resetting is False

    asyncio.run(scenario())


def test_every_resettable_mutation_route_has_the_maintenance_guard(web_client):
    from bandi_cards.season_reset import track_season_mutation

    guarded = set()
    unguarded = set()
    routes = []
    for route in web_client.app.routes:
        included_router = getattr(route, "original_router", None)
        routes.extend(included_router.routes if included_router is not None else [route])
    for route in routes:
        if not isinstance(route, APIRoute):
            continue
        has_guard = any(dependency.call is track_season_mutation for dependency in route.dependant.dependencies)
        target = guarded if has_guard else unguarded
        for method in route.methods or ():
            target.add((method, route.path))

    assert GUARDED_ROUTES <= guarded
    assert UNGUARDED_MUTATING_ROUTES <= unguarded


def test_card_mutations_and_websocket_ticket_return_503_during_reset(signed_in):
    client, _factory, _user_id, csrf = signed_in
    client.post("/api/me/warning", headers={"X-CSRF-Token": csrf})

    with _held_reset(client.app.state.season_reset_coordinator):
        draw = client.post(
            "/api/draw",
            headers={"X-CSRF-Token": csrf},
            json={"idempotency_key": "maintenance-draw"},
        )
        socket_ticket = client.post(
            "/api/auth/websocket-ticket",
            headers={"X-CSRF-Token": csrf},
        )

    assert draw.status_code == 503
    assert draw.json()["detail"] == "시즌 초기화가 진행 중입니다. 잠시 후 다시 시도해주세요."
    assert socket_ticket.status_code == 503


class BroadcastRecorder:
    def __init__(self, *, coordinator=None, error: Exception | None = None) -> None:
        self.messages: list[dict] = []
        self.reset_states: list[bool] = []
        self.coordinator = coordinator
        self.error = error

    async def broadcast_all(self, message: dict) -> None:
        self.messages.append(message)
        if self.coordinator is not None:
            self.reset_states.append(self.coordinator.is_resetting)
        if self.error is not None:
            raise self.error


def test_committed_reset_broadcasts_one_exact_completion_event(admin_signed_in, monkeypatch):
    from bandi_cards.routes import admin_reset

    client, factory, admin_id, csrf = admin_signed_in
    _seed_api_season(factory, admin_id)
    recorder = BroadcastRecorder(coordinator=client.app.state.season_reset_coordinator)
    monkeypatch.setattr(admin_reset, "manager", recorder, raising=False)

    response = client.post(
        "/api/admin/season-reset",
        headers={"X-CSRF-Token": csrf},
        json={"confirmation": CONFIRMATION_TEXT, "operation_id": RESET_OPERATION_ID},
    )

    assert response.status_code == 200
    assert recorder.messages == [
        {"type": "season.reset", "operation_id": RESET_OPERATION_ID}
    ]
    assert recorder.reset_states == [False]


def test_stalled_reset_broadcast_times_out_without_reopening_maintenance(monkeypatch):
    from bandi_cards.routes import admin_reset
    from bandi_cards.season_reset import SeasonResetCoordinator

    class StalledBroadcast:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.cancelled = False

        async def broadcast_all(self, _message: dict) -> None:
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise

    async def completed_reset(_factory, _admin_id, _operation_id):
        return {"completed": True, "replayed": False}

    async def scenario() -> None:
        coordinator = SeasonResetCoordinator()
        broadcaster = StalledBroadcast()
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    season_reset_coordinator=coordinator,
                    session_factory=object(),
                )
            )
        )
        monkeypatch.setattr(admin_reset, "_complete_reset_transaction", completed_reset)
        monkeypatch.setattr(admin_reset, "manager", broadcaster)
        monkeypatch.setattr(admin_reset, "RESET_BROADCAST_TIMEOUT_SECONDS", 0.01, raising=False)

        result = await asyncio.wait_for(
            admin_reset.reset_season(
                admin_reset.SeasonResetBody(
                    confirmation=CONFIRMATION_TEXT,
                    operation_id=RESET_OPERATION_ID,
                ),
                request,
                SimpleNamespace(id=123),
            ),
            timeout=0.2,
        )

        assert result == {"completed": True, "replayed": False}
        assert broadcaster.started.is_set() is True
        assert broadcaster.cancelled is True
        assert coordinator.is_resetting is False

    asyncio.run(scenario())


def test_rolled_back_reset_does_not_broadcast_completion(admin_signed_in, monkeypatch):
    from bandi_cards.routes import admin_reset

    client, factory, admin_id, csrf = admin_signed_in
    _seed_api_season(factory, admin_id)
    recorder = BroadcastRecorder()
    monkeypatch.setattr(admin_reset, "manager", recorder, raising=False)

    def fail_during_reset(db, actor_id, _operation_id):
        db.add(
            AdminAudit(
                admin_id=actor_id,
                action="uncommitted.reset",
                target_type="season",
                target_id=None,
                details_json="{}",
            )
        )
        db.flush()
        raise RuntimeError("forced reset rollback")

    monkeypatch.setattr(admin_reset, "execute_season_reset", fail_during_reset)

    with pytest.raises(RuntimeError, match="forced reset rollback"):
        client.post(
            "/api/admin/season-reset",
            headers={"X-CSRF-Token": csrf},
            json={"confirmation": CONFIRMATION_TEXT, "operation_id": RESET_OPERATION_ID},
        )

    assert recorder.messages == []
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Inventory)) == 1
        assert [audit.action for audit in db.scalars(select(AdminAudit)).all()] == ["old.admin.action"]


def test_broadcast_failure_is_logged_without_reverting_committed_reset(
    admin_signed_in,
    monkeypatch,
    caplog,
):
    from bandi_cards.routes import admin_reset

    client, factory, admin_id, csrf = admin_signed_in
    _seed_api_season(factory, admin_id)
    recorder = BroadcastRecorder(error=RuntimeError("broadcast unavailable"))
    monkeypatch.setattr(admin_reset, "manager", recorder, raising=False)

    with caplog.at_level("ERROR", logger="bandi_cards.routes.admin_reset"):
        response = client.post(
            "/api/admin/season-reset",
            headers={"X-CSRF-Token": csrf},
            json={"confirmation": CONFIRMATION_TEXT, "operation_id": RESET_OPERATION_ID},
        )

    assert response.status_code == 200
    assert recorder.messages == [
        {"type": "season.reset", "operation_id": RESET_OPERATION_ID}
    ]
    assert "Season reset broadcast failed" in caplog.text
    assert "broadcast unavailable" in caplog.text
    with factory() as db:
        audits = db.scalars(select(AdminAudit)).all()
        assert len(audits) == 1
        assert audits[0].action == "season.reset"
        assert audits[0].id == response.json()["audit_id"]
