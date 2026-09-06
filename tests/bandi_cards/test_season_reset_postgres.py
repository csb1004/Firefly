import os
from datetime import date

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from bandi_cards.db import init_database
from bandi_cards.models import (
    AdminAudit,
    Base,
    Card,
    DrawBatch,
    DrawHistory,
    DrawSetting,
    DrawWallet,
    FiveStarEvent,
    Inventory,
    User,
)
from bandi_cards.services.season_reset import (
    SeasonResetLockUnavailable,
    execute_season_reset,
)


@pytest.fixture()
def postgres_factory():
    database_url = os.getenv("TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("TEST_POSTGRES_URL is not configured")
    database_name = make_url(database_url).database or ""
    if not database_name.endswith("_test"):
        pytest.fail("Season reset integration tests require a database ending in _test")

    engine = create_engine(database_url, pool_pre_ping=True)
    Base.metadata.drop_all(engine)
    init_database(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _seed_postgres_season(factory) -> int:
    with factory() as db:
        setting = db.get(DrawSetting, 1)
        setting.daily_draws = 4
        setting.new_user_bonus_tickets = 6
        admin = User(discord_id="pg-admin", username="pg_admin", warning_acknowledged=True)
        player = User(discord_id="pg-player", username="pg_player", warning_acknowledged=True)
        cards = [
            Card(name=f"PG {rarity}성", rarity=rarity, yp=rarity * 100, image_key=f"cards/pg-{rarity}.webp")
            for rarity in range(1, 6)
        ]
        db.add_all([admin, player, *cards])
        db.flush()
        batch = DrawBatch(user_id=admin.id, requested_count=1, idempotency_key="pg-old-batch")
        db.add(batch)
        db.flush()
        history = DrawHistory(
            batch_id=batch.id,
            batch_position=1,
            user_id=admin.id,
            card_id=cards[4].id,
            card_name=cards[4].name,
            card_rarity=5,
            card_yp=500,
            draw_day=date(2026, 9, 1),
            ticket_source="bonus",
            idempotency_key="pg-old-draw",
        )
        db.add(history)
        db.flush()
        db.add_all(
            [
                FiveStarEvent(draw_id=history.id, user_id=admin.id, card_id=cards[4].id),
                Inventory(user_id=admin.id, card_id=cards[4].id, quantity=2),
                DrawWallet(user_id=admin.id, bonus_tickets=99),
                AdminAudit(
                    admin_id=admin.id,
                    action="old.action",
                    target_type="card",
                    target_id=cards[4].id,
                    details_json="{}",
                ),
            ]
        )
        db.commit()
        return admin.id


def test_postgres_lock_rollback_and_foreign_key_reset(postgres_factory):
    admin_id = _seed_postgres_season(postgres_factory)

    first = postgres_factory()
    second = postgres_factory()
    try:
        execute_season_reset(first, admin_id)
        with pytest.raises(SeasonResetLockUnavailable):
            execute_season_reset(second, admin_id)
        second.rollback()
        first.rollback()
    finally:
        first.close()
        second.close()

    with postgres_factory() as db:
        assert db.scalar(select(func.count()).select_from(Inventory)) == 1
        assert db.scalar(select(func.count()).select_from(DrawHistory)) == 1
        assert db.get(DrawWallet, admin_id).bonus_tickets == 99
        assert db.scalar(select(func.count()).select_from(AdminAudit)) == 1

    with postgres_factory() as db:
        result = execute_season_reset(db, admin_id)
        db.commit()

    with postgres_factory() as db:
        assert db.scalar(select(func.count()).select_from(Inventory)) == 0
        assert db.scalar(select(func.count()).select_from(DrawHistory)) == 0
        assert db.scalar(select(func.count()).select_from(FiveStarEvent)) == 0
        wallets = db.scalars(select(DrawWallet).order_by(DrawWallet.user_id)).all()
        assert [wallet.bonus_tickets for wallet in wallets] == [6, 6]
        audits = db.scalars(select(AdminAudit)).all()
        assert [(audit.id, audit.action) for audit in audits] == [(result["audit_id"], "season.reset")]
