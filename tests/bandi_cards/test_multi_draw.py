import random
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from bandi_cards.models import Card, CatalogUnlock, DrawSetting, DrawState, DrawWallet, Inventory, User
from bandi_cards.services.draws import perform_draw_batch


def seed_cards(db):
    for rarity in range(1, 6):
        db.add(Card(name=f"배치 {rarity}성", rarity=rarity, yp=rarity * 10, image_key=f"cards/batch-{rarity}.webp"))


def test_ten_draw_is_sequential_and_idempotent(web_db):
    with web_db() as db:
        user = User(discord_id="batch-user", username="batch", warning_acknowledged=True)
        db.add(user)
        seed_cards(db)
        db.flush()
        db.get(DrawSetting, 1).daily_draws = 10
        db.add(DrawState(user_id=user.id, pulls_since_four_plus=9, pulls_since_five=0))
        db.commit()

        result = perform_draw_batch(db, user.id, "ten-draw-key", count=10, now=datetime(2026, 8, 23, 3, tzinfo=timezone.utc), rng=random.Random(2))
        assert len(result.results) == 10
        assert result.results[0].card.rarity >= 4
        assert result.draws_remaining == 0
        repeated = perform_draw_batch(db, user.id, "ten-draw-key", count=10, now=datetime(2026, 8, 23, 3, tzinfo=timezone.utc), rng=random.Random(99))
        assert repeated.repeated is True
        assert [item.history.id for item in repeated.results] == [item.history.id for item in result.results]
        assert db.query(CatalogUnlock).filter_by(user_id=user.id).count() == db.query(Inventory).filter(Inventory.user_id == user.id, Inventory.quantity > 0).count()


def test_ten_draw_rejects_nine_tickets_without_mutation(web_db):
    with web_db() as db:
        user = User(discord_id="short-user", username="short", warning_acknowledged=True)
        db.add(user)
        seed_cards(db)
        db.flush()
        db.get(DrawSetting, 1).daily_draws = 9
        db.commit()
        with pytest.raises(HTTPException) as error:
            perform_draw_batch(db, user.id, "not-enough-key", count=10)
        assert error.value.status_code == 409
        assert db.query(Inventory).filter_by(user_id=user.id).count() == 0
        assert db.get(DrawWallet, user.id) is None
