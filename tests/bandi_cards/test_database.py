from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bandi_cards.db import DEFAULT_RARITY_PROBABILITIES, init_database
from bandi_cards.models import Card, DrawHistory, Inventory, RaritySetting, User


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    init_database(engine)
    with Session(engine) as session:
        yield session


def add_user_and_card(db: Session):
    user = User(discord_id="123", username="tester")
    card = Card(name="반디", rarity=5, yp=100, image_key="cards/bandi.webp")
    db.add_all([user, card])
    db.commit()
    return user, card


def test_default_rarity_probabilities_are_seeded(db: Session):
    actual = {row.rarity: float(row.probability) for row in db.query(RaritySetting).all()}
    assert actual == DEFAULT_RARITY_PROBABILITIES


def test_inventory_rejects_reserved_quantity_above_quantity(db: Session):
    user, card = add_user_and_card(db)
    db.add(Inventory(user_id=user.id, card_id=card.id, quantity=1, reserved_quantity=2))
    with pytest.raises(IntegrityError):
        db.commit()


def test_daily_draw_is_unique_per_user_and_logical_day(db: Session):
    user, card = add_user_and_card(db)
    common = dict(
        user_id=user.id,
        card_id=card.id,
        card_name=card.name,
        card_rarity=card.rarity,
        card_yp=card.yp,
        draw_day=date(2026, 8, 22),
    )
    db.add(DrawHistory(**common, idempotency_key="one"))
    db.commit()
    db.add(DrawHistory(**common, idempotency_key="two"))
    with pytest.raises(IntegrityError):
        db.commit()
