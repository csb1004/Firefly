from bandi_cards.models import (
    Card,
    CardSet,
    CardSetMember,
    Inventory,
    SetEffect,
    SetEffectTargetCard,
)


def test_user_set_catalog_describes_effects_and_inventory_completion(admin_signed_in):
    client, factory, user_id, _csrf = admin_signed_in
    with factory() as db:
        member = Card(name="세트 구성", rarity=5, yp=500, image_key="cards/member.webp")
        target = Card(name="효과 대상", rarity=1, yp=10, image_key="cards/target.webp")
        card_set = CardSet(name="별빛 세트", active=True)
        db.add_all([member, target, card_set])
        db.flush()
        effect = SetEffect(
            set_id=card_set.id,
            target_scope="selected_cards",
            count_mode="quantity",
            bonus_type="fixed",
            value=50,
            max_count=3,
        )
        db.add_all([
            CardSetMember(set_id=card_set.id, card_id=member.id),
            Inventory(user_id=user_id, card_id=member.id, quantity=1),
            effect,
        ])
        db.flush()
        db.add(SetEffectTargetCard(effect_id=effect.id, card_id=target.id))
        db.commit()
        member_id = member.id

    response = client.get("/api/sets")
    assert response.status_code == 200
    payload = response.json()[0]
    assert payload["name"] == "별빛 세트"
    assert payload["completed"] is True
    assert payload["member_cards"] == [{"id": member_id, "name": "세트 구성", "rarity": 5}]
    assert payload["effects"][0]["target_cards"][0]["name"] == "효과 대상"
    assert payload["effects"][0]["value"] == 50


def test_user_set_catalog_hides_inactive_sets(admin_signed_in):
    client, factory, _user_id, _csrf = admin_signed_in
    with factory() as db:
        db.add(CardSet(name="숨김 세트", active=False))
        db.commit()
    assert client.get("/api/sets").json() == []
