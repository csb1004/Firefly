import pytest
from sqlalchemy.exc import IntegrityError

from bandi_cards.models import (
    Card,
    CardSet,
    CardSetMember,
    CatalogUnlock,
    DrawBatch,
    SetEffect,
    User,
    Inventory,
)
from bandi_cards.services.inventory import discard_card, preview_discard, unlock_card


def test_catalog_unlock_and_draw_batch_are_unique_per_user(web_db):
    with web_db() as db:
        user = User(discord_id="extension-user", username="extension", warning_acknowledged=True)
        card = Card(name="해금 카드", rarity=1, yp=10, image_key="cards/unlock.webp")
        db.add_all([user, card])
        db.commit()
        db.add_all([
            CatalogUnlock(user_id=user.id, card_id=card.id),
            CatalogUnlock(user_id=user.id, card_id=card.id),
        ])
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

        db.add(DrawBatch(user_id=user.id, requested_count=10, idempotency_key="same-batch-key"))
        db.commit()
        db.add(DrawBatch(user_id=user.id, requested_count=10, idempotency_key="same-batch-key"))
        with pytest.raises(IntegrityError):
            db.commit()


def test_set_members_and_effect_values_are_constrained(web_db):
    with web_db() as db:
        card = Card(name="세트 카드", rarity=1, yp=10, image_key="cards/set.webp")
        card_set = CardSet(name="테스트 세트", active=True)
        db.add_all([card, card_set])
        db.flush()
        db.add(CardSetMember(set_id=card_set.id, card_id=card.id))
        db.add(
            SetEffect(
                set_id=card_set.id,
                target_scope="rarity",
                target_rarity=1,
                count_mode="quantity",
                bonus_type="percent",
                value=5,
                max_count=20,
            )
        )
        db.commit()

        db.add(
            SetEffect(
                set_id=card_set.id,
                target_scope="unknown",
                count_mode="once",
                bonus_type="fixed",
                value=1,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_discard_last_copy_preserves_catalog_unlock_and_is_idempotent(web_db):
    with web_db() as db:
        user = User(discord_id="discard-user", username="discard", warning_acknowledged=True)
        card = Card(name="버릴 카드", rarity=3, yp=300, image_key="cards/discard.webp")
        db.add_all([user, card])
        db.flush()
        db.add(Inventory(user_id=user.id, card_id=card.id, quantity=1))
        unlock_card(db, user.id, card.id)
        db.commit()

        preview = preview_discard(db, user.id, card.id, 1)
        assert (preview.yp_before, preview.yp_after) == (300, 0)
        event, repeated = discard_card(db, user.id, card.id, 1, "discard-request")
        assert repeated is False
        assert event.quantity_after == 0
        assert db.get(CatalogUnlock, (user.id, card.id)) is not None

        same, repeated = discard_card(db, user.id, card.id, 1, "discard-request")
        assert repeated is True
        assert same.id == event.id


def test_discard_and_admin_collection_routes(admin_signed_in):
    client, factory, admin_id, csrf = admin_signed_in
    with factory() as db:
        target = User(discord_id="managed-user", username="managed", warning_acknowledged=True)
        card = Card(name="관리 카드", rarity=2, yp=200, image_key="cards/managed.webp")
        db.add_all([target, card])
        db.commit()
        target_id, card_id = target.id, card.id

    changed = client.put(
        f"/api/admin/users/{target_id}/inventory/{card_id}",
        json={"quantity": 2},
        headers={"X-CSRF-Token": csrf},
    )
    assert changed.status_code == 200
    state = changed.json()
    selected = next(item for item in state["cards"] if item["id"] == card_id)
    assert selected["quantity"] == 2
    assert selected["unlocked"] is True

    locked = client.put(
        f"/api/admin/users/{target_id}/catalog/{card_id}",
        json={"unlocked": False},
        headers={"X-CSRF-Token": csrf},
    )
    assert locked.status_code == 200
    assert next(item for item in locked.json()["cards"] if item["id"] == card_id)["unlocked"] is False


def test_admin_can_create_configurable_set(admin_signed_in):
    client, factory, _admin_id, csrf = admin_signed_in
    with factory() as db:
        first = Card(name="세트 A", rarity=1, yp=10, image_key="cards/set-a.webp")
        second = Card(name="세트 B", rarity=2, yp=20, image_key="cards/set-b.webp")
        db.add_all([first, second])
        db.commit()
        ids = [first.id, second.id]
    response = client.post(
        "/api/admin/sets",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "관리 세트",
            "active": True,
            "member_card_ids": ids,
            "effects": [{
                "target_scope": "rarity",
                "target_rarity": 1,
                "target_card_ids": [],
                "bonus_target_scope": "selected_cards",
                "bonus_target_rarity": None,
                "bonus_target_card_ids": [ids[1]],
                "count_mode": "quantity",
                "bonus_type": "fixed",
                "value": 50,
                "max_count": 10,
            }],
        },
    )
    assert response.status_code == 201
    effect = response.json()["effects"][0]
    assert effect["value"] == 50
    assert effect["target_scope"] == "rarity"
    assert effect["bonus_target_scope"] == "selected_cards"
    assert effect["bonus_target_card_ids"] == [ids[1]]
    assert client.get("/api/admin/sets").json()[0]["name"] == "관리 세트"


def test_admin_rejects_duplicate_effect_target_cards(admin_signed_in):
    client, factory, _admin_id, csrf = admin_signed_in
    with factory() as db:
        card = Card(name="중복 대상 카드", rarity=3, yp=30, image_key="cards/duplicate-target.webp")
        db.add(card)
        db.commit()
        card_id = card.id

    response = client.post(
        "/api/admin/sets",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "중복 대상 세트",
            "active": True,
            "member_card_ids": [card_id],
            "effects": [{
                "target_scope": "selected_cards",
                "target_rarity": None,
                "target_card_ids": [card_id, card_id],
                "bonus_target_scope": "selected_cards",
                "bonus_target_rarity": None,
                "bonus_target_card_ids": [card_id],
                "count_mode": "distinct",
                "bonus_type": "fixed",
                "value": 10,
                "max_count": None,
            }],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "적용 횟수 대상 카드가 중복되었습니다."
