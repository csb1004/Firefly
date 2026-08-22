from bandi_cards.models import Card, DrawHistory, DrawSetting, DrawWallet, Inventory, User
from bandi_cards.services.draws import logical_draw_day


def test_catalog_lists_owned_and_unowned_cards_with_progress(signed_in):
    client, factory, user_id, csrf = signed_in
    client.post("/api/me/warning", headers={"X-CSRF-Token": csrf})
    with factory() as db:
        owned = Card(name="보유 카드", rarity=5, yp=500, image_key="cards/owned.webp")
        missing = Card(name="미보유 카드", rarity=4, yp=400, image_key="cards/missing.webp")
        db.add_all([owned, missing])
        db.flush()
        db.add(Inventory(user_id=user_id, card_id=owned.id, quantity=2))
        db.commit()

    response = client.get("/api/catalog")
    assert response.status_code == 200
    assert response.json()["owned_count"] == 1
    assert response.json()["total_count"] == 2
    cards = {card["name"]: card for card in response.json()["cards"]}
    assert cards["보유 카드"]["quantity"] == 2
    assert cards["보유 카드"]["owned"] is True
    assert cards["미보유 카드"]["quantity"] == 0
    assert cards["미보유 카드"]["owned"] is False


def test_admin_configures_daily_draws_grants_tickets_and_resets_today(admin_signed_in):
    client, factory, _admin_id, csrf = admin_signed_in
    with factory() as db:
        target = User(discord_id="ticket-target", username="target", warning_acknowledged=True)
        card = Card(name="관리 테스트 카드", rarity=1, yp=10, image_key="cards/admin-draw.webp")
        db.add_all([target, card])
        db.flush()
        db.add(
            DrawHistory(
                user_id=target.id,
                card_id=card.id,
                card_name=card.name,
                card_rarity=card.rarity,
                card_yp=card.yp,
                draw_day=logical_draw_day(),
                ticket_source="daily",
                idempotency_key="admin-reset-history",
            )
        )
        db.commit()
        target_id = target.id

    configured = client.put(
        "/api/admin/draw-settings",
        headers={"X-CSRF-Token": csrf},
        json={"daily_draws": 3},
    )
    assert configured.status_code == 200
    assert configured.json()["daily_draws"] == 3

    granted = client.post(
        f"/api/admin/users/{target_id}/draw-tickets/grant",
        headers={"X-CSRF-Token": csrf},
        json={"amount": 5},
    )
    assert granted.status_code == 200
    assert granted.json()["bonus_tickets"] == 5
    assert granted.json()["draws_remaining"] == 7

    reset = client.post(
        f"/api/admin/users/{target_id}/draw-tickets/reset-today",
        headers={"X-CSRF-Token": csrf},
    )
    assert reset.status_code == 200
    assert reset.json()["restored"] == 1
    assert reset.json()["draws_remaining"] == 8

    repeated_reset = client.post(
        f"/api/admin/users/{target_id}/draw-tickets/reset-today",
        headers={"X-CSRF-Token": csrf},
    )
    assert repeated_reset.json()["restored"] == 0
    assert repeated_reset.json()["draws_remaining"] == 8

    with factory() as db:
        assert db.get(DrawSetting, 1).daily_draws == 3
        assert db.get(DrawWallet, target_id).bonus_tickets == 5


def test_non_admin_cannot_manage_draw_tickets(signed_in):
    client, _factory, user_id, csrf = signed_in
    client.post("/api/me/warning", headers={"X-CSRF-Token": csrf})
    response = client.post(
        f"/api/admin/users/{user_id}/draw-tickets/grant",
        headers={"X-CSRF-Token": csrf},
        json={"amount": 1},
    )
    assert response.status_code == 403
