import os
import threading
import time
from datetime import date
from queue import Queue

import pytest
from sqlalchemy import create_engine, func, select, text
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
    SeasonResetReceipt,
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


def test_postgres_receipts_survive_later_resets_and_prevent_stale_reexecution(postgres_factory):
    admin_id = _seed_postgres_season(postgres_factory)
    with postgres_factory() as db:
        card_id = db.scalar(select(Card.id).order_by(Card.id))
        first = execute_season_reset(db, admin_id, "postgres-reset-first-0001")
        db.commit()

    with postgres_factory() as db:
        db.add(Inventory(user_id=admin_id, card_id=card_id, quantity=1))
        db.commit()
    with postgres_factory() as db:
        execute_season_reset(db, admin_id, "postgres-reset-second-0001")
        db.commit()

    with postgres_factory() as db:
        db.add(Inventory(user_id=admin_id, card_id=card_id, quantity=3))
        db.commit()
    with postgres_factory() as db:
        replay = execute_season_reset(db, admin_id, "postgres-reset-first-0001")
        db.commit()

    assert replay == {**first, "replayed": True}
    with postgres_factory() as db:
        assert db.scalar(select(Inventory.quantity)) == 3
        assert db.scalar(select(func.count()).select_from(SeasonResetReceipt)) == 2
        assert db.scalar(select(func.count()).select_from(AdminAudit)) == 1


def test_postgres_table_lock_contention_fails_fast_without_mutation(postgres_factory):
    admin_id = _seed_postgres_season(postgres_factory)
    blocker = postgres_factory()
    outcome: Queue[tuple[BaseException | None, float]] = Queue()
    finished = threading.Event()

    def attempt_reset() -> None:
        with postgres_factory() as db:
            started_at = time.monotonic()
            error = None
            try:
                execute_season_reset(db, admin_id)
            except BaseException as exc:  # Captured for assertion in the test thread.
                error = exc
            finally:
                db.rollback()
                outcome.put((error, time.monotonic() - started_at))
                finished.set()

    try:
        blocker.execute(text("LOCK TABLE inventory IN ACCESS EXCLUSIVE MODE"))
        reset_thread = threading.Thread(target=attempt_reset, daemon=True)
        reset_thread.start()
        completed_while_locked = finished.wait(timeout=1.5)
    finally:
        blocker.rollback()
        blocker.close()

    reset_thread.join(timeout=5)
    assert completed_while_locked, "season reset waited on a conflicting table lock"
    assert not reset_thread.is_alive()
    error, elapsed = outcome.get_nowait()
    assert isinstance(error, SeasonResetLockUnavailable)
    assert elapsed < 1.5

    with postgres_factory() as db:
        assert db.scalar(select(func.count()).select_from(Inventory)) == 1
        assert db.scalar(select(func.count()).select_from(DrawHistory)) == 1
        assert db.get(DrawWallet, admin_id).bonus_tickets == 99
        assert db.scalar(select(func.count()).select_from(AdminAudit)) == 1
