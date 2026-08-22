import random
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from bandi_cards.models import Card, DailyDrawAllowance, DrawSetting, DrawState, DrawWallet, Inventory, User
from bandi_cards.services.draws import (
    collection_yp,
    five_star_probability,
    logical_draw_day,
    perform_draw,
    rarity_probabilities,
)


def seed_cards(db):
    cards = []
    for rarity in range(1, 6):
        card = Card(name=f"{rarity}성 카드", rarity=rarity, yp=rarity * 100, image_key=f"cards/{rarity}.webp")
        db.add(card)
        cards.append(card)
    db.commit()
    return cards


def test_kst_draw_day_resets_at_five_am():
    assert logical_draw_day(datetime(2026, 8, 21, 19, 59, tzinfo=timezone.utc)).isoformat() == "2026-08-21"
    assert logical_draw_day(datetime(2026, 8, 21, 20, 0, tzinfo=timezone.utc)).isoformat() == "2026-08-22"


def test_soft_and_hard_pity_probabilities():
    assert five_star_probability(73, 0.6) == pytest.approx(6.6)
    assert five_star_probability(88, 0.6) == pytest.approx(96.6)
    assert five_star_probability(89, 0.6) == 100.0


def test_four_star_guarantee_is_applied_only_after_five_star_roll():
    configured = {1: 45, 2: 30, 3: 19.3, 4: 5.1, 5: 0.6}
    chances = rarity_probabilities(9, 73, configured)
    assert chances[5] == pytest.approx(6.6)
    assert chances[4] == pytest.approx(93.4)
    assert chances[1] == chances[2] == chances[3] == 0
    assert sum(chances.values()) == pytest.approx(100)


def test_soft_pity_preserves_lower_rarity_ratios():
    configured = {1: 45, 2: 30, 3: 19.3, 4: 5.1, 5: 0.6}
    chances = rarity_probabilities(0, 73, configured)
    assert chances[1] / chances[2] == pytest.approx(45 / 30)
    assert sum(chances.values()) == pytest.approx(100)


def test_fresh_user_can_load_draw_status_and_card_probabilities(signed_in):
    client, factory, _user_id, csrf = signed_in
    client.post("/api/me/warning", headers={"X-CSRF-Token": csrf})
    with factory() as db:
        cards = seed_cards(db)

    status = client.get("/api/draw/status")
    probabilities = client.get("/api/probabilities/current")

    assert status.status_code == 200
    assert status.json() == {
        "eligible": True,
        "draws_remaining": 1,
        "daily_remaining": 1,
        "bonus_tickets": 0,
        "four_remaining": 10,
        "five_remaining": 90,
    }
    assert probabilities.status_code == 200
    assert {item["card_id"] for item in probabilities.json()["cards"]} == {card.id for card in cards}

    drawn = client.post(
        "/api/draw",
        json={"idempotency_key": "fresh-user-draw"},
        headers={"X-CSRF-Token": csrf},
    )
    assert drawn.status_code == 200
    assert client.get("/api/draw/status").json()["eligible"] is False


def test_daily_limit_allows_multiple_draws_and_bonus_tickets_are_consumed_once(web_db):
    with web_db() as db:
        user = User(discord_id="multi-draw-user", username="multi", warning_acknowledged=True)
        db.add(user)
        seed_cards(db)
        db.get(DrawSetting, 1).daily_draws = 2
        db.add(DrawWallet(user_id=user.id, bonus_tickets=1))
        db.commit()

        first_day = datetime(2026, 8, 23, 3, tzinfo=timezone.utc)
        results = [
            perform_draw(db, user.id, f"multi-draw-{index}", now=first_day, rng=random.Random(index))
            for index in range(3)
        ]
        assert [result.history.ticket_source for result in results] == ["daily", "daily", "bonus"]
        assert db.get(DrawWallet, user.id).bonus_tickets == 0

        with pytest.raises(HTTPException) as error:
            perform_draw(db, user.id, "multi-draw-fourth", now=first_day)
        assert error.value.status_code == 409

        next_day = datetime(2026, 8, 24, 3, tzinfo=timezone.utc)
        perform_draw(db, user.id, "next-day-one", now=next_day, rng=random.Random(4))
        perform_draw(db, user.id, "next-day-two", now=next_day, rng=random.Random(5))
        with pytest.raises(HTTPException):
            perform_draw(db, user.id, "next-day-no-bonus", now=next_day)


def test_daily_allowance_can_restore_draws_without_resetting_pity(web_db):
    with web_db() as db:
        user = User(discord_id="reset-user", username="reset", warning_acknowledged=True)
        db.add(user)
        seed_cards(db)
        db.commit()
        now = datetime(2026, 8, 23, 3, tzinfo=timezone.utc)
        perform_draw(db, user.id, "before-reset", now=now, rng=random.Random(1))
        pity_before = db.get(DrawState, user.id).pulls_since_five
        db.add(DailyDrawAllowance(user_id=user.id, draw_day=logical_draw_day(now), extra_draws=1))
        db.commit()

        perform_draw(db, user.id, "after-reset", now=now, rng=random.Random(2))
        assert db.get(DrawState, user.id).pulls_since_five >= pity_before


def test_daily_draw_is_idempotent_and_collection_yp_counts_card_once(web_db):
    with web_db() as db:
        user = User(discord_id="draw-user", username="draw", warning_acknowledged=True)
        db.add(user)
        seed_cards(db)
        db.commit()
        first = perform_draw(
            db,
            user.id,
            "same-request-key",
            now=datetime(2026, 8, 22, 3, tzinfo=timezone.utc),
            rng=random.Random(1),
        )
        repeated = perform_draw(
            db,
            user.id,
            "same-request-key",
            now=datetime(2026, 8, 22, 3, tzinfo=timezone.utc),
            rng=random.Random(999),
        )
        assert repeated.history.id == first.history.id
        assert repeated.repeated is True
        inventory = db.get(Inventory, (user.id, first.card.id))
        assert inventory.quantity == 1
        inventory.quantity = 5
        db.commit()
        assert collection_yp(db, user.id) == first.card.yp

        with pytest.raises(HTTPException) as error:
            perform_draw(
                db,
                user.id,
                "different-key",
                now=datetime(2026, 8, 22, 3, tzinfo=timezone.utc),
            )
        assert error.value.status_code == 409


def test_ninetieth_draw_is_five_star_and_resets_both_counters(web_db):
    with web_db() as db:
        user = User(discord_id="pity-user", username="pity", warning_acknowledged=True)
        db.add(user)
        seed_cards(db)
        db.flush()
        db.add(DrawState(user_id=user.id, pulls_since_four_plus=4, pulls_since_five=89))
        db.commit()

        result = perform_draw(
            db,
            user.id,
            "hard-pity-request",
            now=datetime(2026, 8, 23, 3, tzinfo=timezone.utc),
            rng=random.Random(4),
        )
        state = db.get(DrawState, user.id)
        assert result.card.rarity == 5
        assert state.pulls_since_four_plus == 0
        assert state.pulls_since_five == 0
        assert result.four_remaining == 10
        assert result.five_remaining == 90
