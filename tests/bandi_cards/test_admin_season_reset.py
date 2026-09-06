import asyncio
import json
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from bandi_cards.models import (
    AdminAudit,
    Card,
    CatalogUnlock,
    DrawSetting,
    DrawWallet,
    Inventory,
    User,
)
from bandi_cards.services.season_reset import CONFIRMATION_TEXT


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
        json={"confirmation": CONFIRMATION_TEXT},
    ).status_code == 403


def test_reset_requires_csrf_and_exact_confirmation_without_changing_data(admin_signed_in):
    client, factory, admin_id, csrf = admin_signed_in
    _seed_api_season(factory, admin_id)

    assert client.post(
        "/api/admin/season-reset",
        json={"confirmation": CONFIRMATION_TEXT},
    ).status_code == 403
    wrong = client.post(
        "/api/admin/season-reset",
        headers={"X-CSRF-Token": csrf},
        json={"confirmation": "시즌 초기화"},
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
        json={"confirmation": CONFIRMATION_TEXT},
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
        json={"confirmation": CONFIRMATION_TEXT},
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

        async def held_reset(_factory, _admin_id):
            entered.set()
            await release.wait()
            return {"completed": True}

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
                admin_reset.SeasonResetBody(confirmation=CONFIRMATION_TEXT),
                request,
                admin,
            )
        )
        await entered.wait()

        with pytest.raises(HTTPException) as caught:
            await admin_reset.reset_season(
                admin_reset.SeasonResetBody(confirmation=CONFIRMATION_TEXT),
                request,
                admin,
            )
        assert caught.value.status_code == 409

        release.set()
        assert await first == {"completed": True}

    asyncio.run(scenario())


def test_repeated_request_cancellation_waits_for_database_worker(monkeypatch):
    from bandi_cards.routes import admin_reset
    from bandi_cards.season_reset import SeasonResetCoordinator

    worker_entered = threading.Event()
    release_worker = threading.Event()

    def held_commit(_factory, _admin_id):
        worker_entered.set()
        release_worker.wait(timeout=5)
        return {"completed": True}

    monkeypatch.setattr(admin_reset, "_commit_reset", held_commit)

    async def scenario() -> None:
        coordinator = SeasonResetCoordinator()

        async def request() -> dict:
            async with coordinator.reset():
                return await admin_reset._complete_reset_transaction(object(), 123)

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
