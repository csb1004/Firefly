import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, inspect, select

from bandi_cards.models import (
    AdminAudit,
    Base,
    Card,
    CardSet,
    CardSetMember,
    CatalogUnlock,
    DailyDrawAllowance,
    DiscardEvent,
    DrawBatch,
    DrawHistory,
    DrawSetting,
    DrawState,
    DrawWallet,
    FiveStarEvent,
    Gift,
    ImageCleanup,
    Inventory,
    NotificationOutbox,
    OAuthAttempt,
    ProbabilityAudit,
    RaritySetting,
    SetEffect,
    SetEffectBonusTargetCard,
    SetEffectTargetCard,
    TradeOffer,
    TradeRequest,
    TradeRoom,
    User,
    WebSession,
    WebSocketTicket,
)
from bandi_cards.services import season_reset
from bandi_cards.services.draws import draw_counters, draw_ticket_status
from bandi_cards.services.season_reset import (
    RESET_MODELS,
    SeasonResetConfigurationInvalid,
    SeasonResetLockUnavailable,
    execute_season_reset,
    preview_season_reset,
)


UTC = timezone.utc
SEEDED_AT = datetime(2026, 9, 1, 12, 30, tzinfo=UTC)
DRAW_DAY = date(2026, 9, 1)
PRESERVED_MODELS = (
    User,
    WebSession,
    OAuthAttempt,
    RaritySetting,
    Card,
    CardSet,
    CardSetMember,
    SetEffect,
    SetEffectTargetCard,
    SetEffectBonusTargetCard,
    DrawSetting,
    ImageCleanup,
)


@dataclass(frozen=True)
class SeededSeason:
    admin_id: int
    player_id: int
    card_ids: tuple[str, ...]
    session_token_hash: str
    oauth_state_hash: str
    old_notification_payload: str


def _seed_season_data(
    factory,
    *,
    daily_draws: int = 3,
    new_user_bonus_tickets: int = 7,
) -> SeededSeason:
    with factory() as db:
        setting = db.get(DrawSetting, 1)
        setting.daily_draws = daily_draws
        setting.new_user_bonus_tickets = new_user_bonus_tickets
        probabilities = {1: 45, 2: 30, 3: Decimal("19.3"), 4: Decimal("5.1"), 5: Decimal("0.6")}
        for rarity, probability in probabilities.items():
            row = db.get(RaritySetting, rarity)
            row.probability = probability
            row.updated_at = SEEDED_AT

        admin = User(
            discord_id="season-admin",
            username="admin_before",
            global_name="관리자 이름",
            avatar_hash="admin-avatar",
            warning_acknowledged=True,
            accepts_gifts=False,
            accepts_trades=True,
            profile_synced_at=SEEDED_AT,
            profile_sync_attempted_at=SEEDED_AT,
            profile_sync_error="old profile error",
            created_at=SEEDED_AT,
            updated_at=SEEDED_AT,
        )
        player = User(
            discord_id="season-player",
            username="player_before",
            global_name="플레이어 이름",
            avatar_hash="player-avatar",
            warning_acknowledged=True,
            accepts_gifts=True,
            accepts_trades=False,
            profile_synced_at=SEEDED_AT,
            profile_sync_attempted_at=SEEDED_AT,
            profile_sync_error=None,
            created_at=SEEDED_AT,
            updated_at=SEEDED_AT,
        )
        cards = [
            Card(
                id=f"00000000-0000-0000-0000-00000000000{rarity}",
                name=f"보존 카드 {rarity}성",
                rarity=rarity,
                yp=rarity * 111,
                weight=Decimal(f"{rarity}.25"),
                active=True,
                image_key=f"cards/preserved-{rarity}.webp",
                created_at=SEEDED_AT,
                updated_at=SEEDED_AT,
            )
            for rarity in range(1, 6)
        ]
        db.add_all([admin, player, *cards])
        db.flush()

        card_set = CardSet(
            id="10000000-0000-0000-0000-000000000001",
            name="보존 세트",
            active=True,
            created_at=SEEDED_AT,
            updated_at=SEEDED_AT,
        )
        effect = SetEffect(
            id="20000000-0000-0000-0000-000000000001",
            set_id=card_set.id,
            target_scope="selected_cards",
            target_rarity=None,
            bonus_target_scope="selected_cards",
            bonus_target_rarity=None,
            count_mode="quantity",
            bonus_type="percent",
            value=Decimal("12.5000"),
            max_count=4,
            position=3,
        )
        batch = DrawBatch(
            id="30000000-0000-0000-0000-000000000001",
            user_id=admin.id,
            requested_count=1,
            idempotency_key="old-draw-batch",
            created_at=SEEDED_AT,
        )
        history = DrawHistory(
            id="40000000-0000-0000-0000-000000000001",
            batch_id=batch.id,
            batch_position=1,
            user_id=admin.id,
            card_id=cards[4].id,
            card_name=cards[4].name,
            card_rarity=5,
            card_yp=cards[4].yp,
            draw_day=DRAW_DAY,
            ticket_source="bonus",
            idempotency_key="old-draw-history",
            drawn_at=SEEDED_AT,
        )
        room = TradeRoom(
            id="50000000-0000-0000-0000-000000000001",
            inviter_id=admin.id,
            invitee_id=player.id,
            status="negotiating",
            offer_version=2,
            inviter_accepted_version=2,
            invitee_accepted_version=None,
            reconnect_deadline=SEEDED_AT + timedelta(minutes=1),
            created_at=SEEDED_AT,
            updated_at=SEEDED_AT,
        )
        db.add_all([card_set, batch, room])
        db.flush()
        db.add(effect)
        db.flush()
        db.add(history)
        db.flush()
        old_notification_payload = '{"old":"season"}'
        db.add_all(
            [
                CardSetMember(set_id=card_set.id, card_id=cards[4].id),
                SetEffectTargetCard(effect_id=effect.id, card_id=cards[0].id),
                SetEffectBonusTargetCard(effect_id=effect.id, card_id=cards[4].id),
                WebSession(
                    token_hash="session-token-hash",
                    user_id=admin.id,
                    created_at=SEEDED_AT,
                    last_seen_at=SEEDED_AT,
                    expires_at=SEEDED_AT + timedelta(days=30),
                ),
                OAuthAttempt(
                    state_hash="oauth-state-hash",
                    verifier="oauth-verifier",
                    created_at=SEEDED_AT,
                    expires_at=SEEDED_AT + timedelta(minutes=10),
                ),
                ImageCleanup(
                    id="60000000-0000-0000-0000-000000000001",
                    image_key="cards/orphaned-but-preserved.webp",
                    attempts=2,
                    available_at=SEEDED_AT,
                    last_error="retry later",
                ),
                Inventory(user_id=admin.id, card_id=cards[4].id, quantity=3, reserved_quantity=1, updated_at=SEEDED_AT),
                Inventory(user_id=player.id, card_id=cards[3].id, quantity=2, reserved_quantity=0, updated_at=SEEDED_AT),
                CatalogUnlock(user_id=admin.id, card_id=cards[4].id, unlocked_at=SEEDED_AT),
                CatalogUnlock(user_id=player.id, card_id=cards[3].id, unlocked_at=SEEDED_AT),
                DiscardEvent(
                    id="70000000-0000-0000-0000-000000000001",
                    user_id=admin.id,
                    card_id=cards[0].id,
                    card_name=cards[0].name,
                    quantity=1,
                    quantity_after=0,
                    yp_before=111,
                    yp_after=0,
                    idempotency_key="old-discard",
                    created_at=SEEDED_AT,
                ),
                DrawState(user_id=admin.id, pulls_since_four_plus=8, pulls_since_five=73, updated_at=SEEDED_AT),
                DrawState(user_id=player.id, pulls_since_four_plus=4, pulls_since_five=22, updated_at=SEEDED_AT),
                DrawWallet(user_id=admin.id, bonus_tickets=99, updated_at=SEEDED_AT),
                DrawWallet(user_id=player.id, bonus_tickets=8, updated_at=SEEDED_AT),
                DailyDrawAllowance(user_id=admin.id, draw_day=DRAW_DAY, extra_draws=6, updated_at=SEEDED_AT),
                FiveStarEvent(
                    id="80000000-0000-0000-0000-000000000001",
                    draw_id=history.id,
                    user_id=admin.id,
                    card_id=cards[4].id,
                    created_at=SEEDED_AT,
                ),
                Gift(
                    id="90000000-0000-0000-0000-000000000001",
                    sender_id=admin.id,
                    receiver_id=player.id,
                    card_id=cards[4].id,
                    card_name=cards[4].name,
                    quantity=1,
                    sender_yp_change=-555,
                    receiver_yp_change=555,
                    idempotency_key="old-gift",
                    created_at=SEEDED_AT,
                ),
                TradeOffer(room_id=room.id, user_id=admin.id, card_id=cards[4].id, quantity=1),
                TradeRequest(
                    id="a0000000-0000-0000-0000-000000000001",
                    room_id=room.id,
                    requester_id=player.id,
                    target_id=admin.id,
                    kind="card",
                    card_id=cards[4].id,
                    quantity=1,
                    message="old request",
                    created_at=SEEDED_AT,
                ),
                WebSocketTicket(
                    token_hash="websocket-token-hash",
                    user_id=player.id,
                    expires_at=SEEDED_AT + timedelta(minutes=1),
                    consumed_at=None,
                ),
                NotificationOutbox(
                    id="b0000000-0000-0000-0000-000000000001",
                    recipient_discord_id=player.discord_id,
                    kind="gift.received",
                    payload=old_notification_payload,
                    status="pending",
                    attempts=1,
                    available_at=SEEDED_AT,
                    claimed_at=None,
                    delivered_at=None,
                    last_error="old failure",
                    created_at=SEEDED_AT,
                ),
                ProbabilityAudit(
                    id="c0000000-0000-0000-0000-000000000001",
                    admin_id=admin.id,
                    before_json='{"5":0.5}',
                    after_json='{"5":0.6}',
                    created_at=SEEDED_AT,
                ),
                AdminAudit(
                    id="d0000000-0000-0000-0000-000000000001",
                    admin_id=admin.id,
                    action="old.action",
                    target_type="card",
                    target_id=cards[0].id,
                    details_json='{"old":true}',
                    created_at=SEEDED_AT,
                ),
            ]
        )
        db.commit()
        return SeededSeason(
            admin_id=admin.id,
            player_id=player.id,
            card_ids=tuple(card.id for card in cards),
            session_token_hash="session-token-hash",
            oauth_state_hash="oauth-state-hash",
            old_notification_payload=old_notification_payload,
        )


def _normalize(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _snapshot_models(factory, models=tuple(mapper.class_ for mapper in Base.registry.mappers)) -> dict:
    snapshot = {}
    with factory() as db:
        for model in sorted(models, key=lambda item: item.__tablename__):
            mapper = inspect(model)
            columns = tuple(column.key for column in mapper.columns)
            rows = db.scalars(select(model).order_by(*mapper.primary_key)).all()
            snapshot[model.__tablename__] = [
                tuple(_normalize(getattr(row, column)) for column in columns)
                for row in rows
            ]
    return snapshot


def test_reset_deletes_only_season_data_and_reissues_configured_bonus(web_db):
    seeded = _seed_season_data(web_db)
    preserved_before = _snapshot_models(web_db, PRESERVED_MODELS)

    with web_db() as db:
        preview = preview_season_reset(db)
        result = execute_season_reset(db, seeded.admin_id)
        db.commit()

    assert preview["delete_counts"] == {
        "five_star_events": 1,
        "draw_history": 1,
        "draw_batches": 1,
        "trade_offers": 1,
        "trade_requests": 1,
        "trade_rooms": 1,
        "gifts": 1,
        "discard_events": 1,
        "inventory": 2,
        "catalog_unlocks": 2,
        "draw_states": 2,
        "daily_draw_allowances": 1,
        "draw_wallets": 2,
        "websocket_tickets": 1,
        "notification_outbox": 1,
        "probability_audit": 1,
        "admin_audit": 1,
    }
    assert result["delete_counts"] == preview["delete_counts"]
    assert preview["summary"] == {"inventory_copies": 5, "trade_records": 3, "audit_records": 2}
    assert preview["grant"] == {"eligible_users": 2, "tickets_per_user": 7, "total_tickets": 14}
    assert result["grant"] == {"granted_users": 2, "tickets_per_user": 7, "total_tickets": 14}
    assert result["preserved"] == preview["preserved"]
    assert _snapshot_models(web_db, PRESERVED_MODELS) == preserved_before

    with web_db() as db:
        for model in (item for item in RESET_MODELS if item not in (DrawWallet, AdminAudit)):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        wallets = db.scalars(select(DrawWallet).order_by(DrawWallet.user_id)).all()
        assert [(wallet.user_id, wallet.bonus_tickets) for wallet in wallets] == [
            (seeded.admin_id, 7),
            (seeded.player_id, 7),
        ]
        assert draw_ticket_status(db, seeded.admin_id)["daily_remaining"] == 3
        assert draw_ticket_status(db, seeded.admin_id)["bonus_tickets"] == 7
        assert db.get(DrawState, seeded.admin_id) is None
        assert draw_counters(None) == (0, 0)

        audits = db.scalars(select(AdminAudit)).all()
        assert len(audits) == 1
        audit = audits[0]
        assert audit.action == "season.reset"
        assert audit.admin_id == seeded.admin_id
        assert audit.target_type == "season"
        assert audit.target_id == result["completed_at"]
        assert audit.id == result["audit_id"]
        assert json.loads(audit.details_json) == {
            "delete_counts": result["delete_counts"],
            "grant": result["grant"],
            "preserved": result["preserved"],
        }


def test_preview_is_read_only_and_reports_preserved_configuration(web_db):
    _seed_season_data(web_db, daily_draws=2, new_user_bonus_tickets=4)
    before = _snapshot_models(web_db)

    with web_db() as db:
        preview = preview_season_reset(db)

    assert _snapshot_models(web_db) == before
    assert preview["preserved"] == {
        "users": 2,
        "cards": 5,
        "card_sets": 1,
        "rarity_settings": 5,
        "image_cleanup": 1,
        "draw_settings": {"daily_draws": 2, "new_user_bonus_tickets": 4},
    }


def test_zero_new_user_benefit_creates_no_wallet_rows(web_db):
    seeded = _seed_season_data(web_db, daily_draws=1, new_user_bonus_tickets=0)
    with web_db() as db:
        execute_season_reset(db, seeded.admin_id)
        db.commit()
    with web_db() as db:
        assert db.scalar(select(func.count()).select_from(DrawWallet)) == 0
        assert draw_ticket_status(db, seeded.player_id)["daily_remaining"] == 1


def test_reset_failure_after_reseed_rolls_back_every_field(web_db, monkeypatch):
    seeded = _seed_season_data(web_db)
    before = _snapshot_models(web_db)

    def fail_after_reseed(*_args, **_kwargs):
        raise RuntimeError("injected")

    monkeypatch.setattr(season_reset, "_append_reset_audit", fail_after_reseed)
    with web_db() as db:
        with pytest.raises(RuntimeError, match="injected"):
            execute_season_reset(db, seeded.admin_id)
        db.rollback()

    assert _snapshot_models(web_db) == before


def test_lock_unavailable_changes_nothing(web_db, monkeypatch):
    seeded = _seed_season_data(web_db)
    before = _snapshot_models(web_db)

    def unavailable(_db):
        raise SeasonResetLockUnavailable

    monkeypatch.setattr(season_reset, "_acquire_postgres_locks", unavailable)
    with web_db() as db:
        with pytest.raises(SeasonResetLockUnavailable):
            execute_season_reset(db, seeded.admin_id)
        db.rollback()

    assert _snapshot_models(web_db) == before


@pytest.mark.parametrize("operation", [preview_season_reset, execute_season_reset])
def test_missing_draw_setting_is_rejected_without_mutation(web_db, operation):
    seeded = _seed_season_data(web_db)
    with web_db() as db:
        db.delete(db.get(DrawSetting, 1))
        db.commit()
    before = _snapshot_models(web_db)

    with web_db() as db:
        with pytest.raises(SeasonResetConfigurationInvalid, match="뽑기 지급 설정"):
            if operation is execute_season_reset:
                operation(db, seeded.admin_id)
            else:
                operation(db)
        db.rollback()

    assert _snapshot_models(web_db) == before


@pytest.mark.parametrize("operation", [preview_season_reset, execute_season_reset])
def test_invalid_probability_pool_is_rejected_without_mutation(web_db, operation):
    seeded = _seed_season_data(web_db)
    with web_db() as db:
        db.get(Card, seeded.card_ids[4]).active = False
        db.commit()
    before = _snapshot_models(web_db)

    with web_db() as db:
        with pytest.raises(SeasonResetConfigurationInvalid, match="활성 카드"):
            if operation is execute_season_reset:
                operation(db, seeded.admin_id)
            else:
                operation(db)
        db.rollback()

    assert _snapshot_models(web_db) == before
