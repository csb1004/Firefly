import io
from types import SimpleNamespace

from PIL import Image

from bandi_cards.models import Card, DrawHistory, Inventory, User
from bandi_cards.services.card_assets import CardAssetStore


def image_bytes(size=(400, 400), image_format="PNG"):
    output = io.BytesIO()
    Image.new("RGB", size, "#7c5cff").save(output, format=image_format)
    return output.getvalue()


def test_non_admin_cannot_open_admin_catalog(signed_in):
    client, _factory, _user_id, csrf = signed_in
    client.post("/api/me/warning", headers={"X-CSRF-Token": csrf})
    assert client.get("/api/admin/cards").status_code == 403


def test_admin_creates_card_and_invalid_probability_pool_is_rejected(admin_signed_in, monkeypatch):
    client, _factory, _admin_id, csrf = admin_signed_in

    async def fake_save(*_args, **_kwargs):
        return "cards/test.webp"

    monkeypatch.setattr("bandi_cards.routes.cards.asset_store.save", fake_save)
    response = client.post(
        "/api/admin/cards",
        headers={"X-CSRF-Token": csrf},
        data={"name": "히메코", "rarity": "5", "yp": "500", "active": "true"},
        files={"image": ("himeko.png", image_bytes(), "image/png")},
    )
    assert response.status_code == 201
    assert response.json()["rarity"] == 5

    invalid = client.put(
        "/api/admin/probabilities",
        headers={"X-CSRF-Token": csrf},
        json={"probabilities": {"1": 45, "2": 30, "3": 19.3, "4": 5, "5": 0.6}},
    )
    assert invalid.status_code == 422


def test_card_asset_is_normalized_to_three_by_four_webp(tmp_path, monkeypatch):
    import bandi_cards.services.card_assets as module

    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(
            s3_endpoint_url="",
            s3_bucket_name="",
            s3_access_key_id="",
            s3_secret_access_key="",
            s3_region="auto",
            upload_dir=tmp_path,
        ),
    )
    store = CardAssetStore()

    class Upload:
        content_type = "image/png"

        async def read(self, _limit):
            return image_bytes((1200, 500))

    import asyncio

    key = asyncio.run(store.save(Upload()))
    with Image.open(tmp_path / key) as normalized:
        assert normalized.format == "WEBP"
        assert normalized.size == (900, 1200)


def test_permanent_delete_keeps_draw_snapshot_and_removes_inventory(admin_signed_in):
    client, factory, admin_id, csrf = admin_signed_in
    with factory() as db:
        owner = User(discord_id="555", username="owner", warning_acknowledged=True)
        card = Card(name="삭제 대상", rarity=5, yp=999, image_key="cards/delete.webp")
        db.add_all([owner, card])
        db.flush()
        db.add(Inventory(user_id=owner.id, card_id=card.id, quantity=3))
        history = DrawHistory(
            user_id=owner.id,
            card_id=card.id,
            card_name=card.name,
            card_rarity=card.rarity,
            card_yp=card.yp,
            draw_day=__import__("datetime").date(2026, 8, 22),
            idempotency_key="delete-history",
        )
        db.add(history)
        db.commit()
        card_id = card.id
        history_id = history.id

    response = client.request(
        "DELETE",
        f"/api/admin/cards/{card_id}",
        headers={"X-CSRF-Token": csrf},
        json={"confirm_name": "삭제 대상"},
    )
    assert response.status_code == 204
    with factory() as db:
        assert db.get(Card, card_id) is None
        assert db.get(Inventory, (2, card_id)) is None
        history = db.get(DrawHistory, history_id)
        assert history.card_id is None
        assert history.card_name == "삭제 대상"


def test_card_update_rejects_duplicate_name_and_emptying_configured_rarity(admin_signed_in):
    client, factory, _admin_id, csrf = admin_signed_in
    with factory() as db:
        first = Card(name="첫 카드", rarity=4, yp=100, image_key="cards/first.webp")
        second = Card(name="둘째 카드", rarity=5, yp=200, image_key="cards/second.webp")
        db.add_all([first, second])
        db.commit()
        first_id = first.id

    duplicate = client.put(
        f"/api/admin/cards/{first_id}",
        headers={"X-CSRF-Token": csrf},
        data={"name": "둘째 카드", "rarity": 4, "yp": 100, "active": "true"},
    )
    assert duplicate.status_code == 409

    deactivate_last = client.put(
        f"/api/admin/cards/{first_id}",
        headers={"X-CSRF-Token": csrf},
        data={"name": "첫 카드", "rarity": 4, "yp": 100, "active": "false"},
    )
    assert deactivate_last.status_code == 409
