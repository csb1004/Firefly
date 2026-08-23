from bandi_cards.models import Card, CardSet, CardSetMember, Inventory, SetEffect, User
from bandi_cards.services.set_effects import effective_yp


def test_base_yp_counts_every_copy_while_set_activates_once(web_db):
    with web_db() as db:
        user = User(discord_id="copy-user", username="copies", warning_acknowledged=True)
        card = Card(name="중복 카드", rarity=4, yp=100, image_key="cards/copies.webp")
        card_set = CardSet(name="중복되지 않는 세트", active=True)
        db.add_all([user, card, card_set])
        db.flush()
        db.add_all([
            Inventory(user_id=user.id, card_id=card.id, quantity=3),
            CardSetMember(set_id=card_set.id, card_id=card.id),
            SetEffect(set_id=card_set.id, target_scope="collection", count_mode="once", bonus_type="fixed", value=50),
        ])
        db.commit()

        result = effective_yp(db, user.id)
        assert result.base_yp == 300
        assert result.fixed_bonus == 50
        assert result.total_yp == 350
        assert result.active_sets == ("중복되지 않는 세트",)


def test_fixed_then_linear_percent_effects_use_inventory_counts(web_db):
    with web_db() as db:
        user = User(discord_id="set-user", username="set", warning_acknowledged=True)
        member = Card(name="구성 카드", rarity=5, yp=1000, image_key="cards/member.webp")
        one_star = Card(name="1성 카드", rarity=1, yp=0, image_key="cards/one.webp")
        card_set = CardSet(name="효과 세트", active=True)
        db.add_all([user, member, one_star, card_set])
        db.flush()
        db.add_all([
            Inventory(user_id=user.id, card_id=member.id, quantity=1),
            Inventory(user_id=user.id, card_id=one_star.id, quantity=30),
            CardSetMember(set_id=card_set.id, card_id=member.id),
            SetEffect(set_id=card_set.id, target_scope="collection", count_mode="once", bonus_type="fixed", value=100),
            SetEffect(set_id=card_set.id, target_scope="rarity", target_rarity=1, count_mode="quantity", bonus_type="percent", value=5, max_count=3),
        ])
        db.commit()

        result = effective_yp(db, user.id)
        assert result.base_yp == 1000
        assert result.fixed_bonus == 100
        assert result.percent_bonus == 15
        assert result.total_yp == 1265
        assert result.active_sets == ("효과 세트",)


def test_set_deactivates_when_last_member_copy_is_missing(web_db):
    with web_db() as db:
        user = User(discord_id="missing-member", username="missing", warning_acknowledged=True)
        card = Card(name="없는 구성 카드", rarity=1, yp=100, image_key="cards/missing-member.webp")
        card_set = CardSet(name="미완성 세트", active=True)
        db.add_all([user, card, card_set])
        db.flush()
        db.add_all([
            Inventory(user_id=user.id, card_id=card.id, quantity=0),
            CardSetMember(set_id=card_set.id, card_id=card.id),
            SetEffect(set_id=card_set.id, target_scope="collection", count_mode="once", bonus_type="fixed", value=500),
        ])
        db.commit()
        assert effective_yp(db, user.id).total_yp == 0
