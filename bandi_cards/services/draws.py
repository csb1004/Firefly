from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Card,
    DailyDrawAllowance,
    DrawBatch,
    DrawHistory,
    DrawSetting,
    DrawState,
    DrawWallet,
    FiveStarEvent,
    Inventory,
    User,
    utcnow,
)
from .probabilities import base_probabilities
from .inventory import unlock_card
from .set_effects import effective_yp


KST = ZoneInfo("Asia/Seoul")


def logical_draw_day(now: datetime | None = None) -> date:
    now = now or utcnow()
    local = now.astimezone(KST)
    if local.time() < time(5, 0):
        local -= timedelta(days=1)
    return local.date()


def five_star_probability(pulls_since_five: int, base_five: float) -> float:
    draw_number = pulls_since_five + 1
    if draw_number >= 90:
        return 100.0
    if draw_number >= 74:
        return min(100.0, base_five + 6.0 * (draw_number - 73))
    return base_five


def rarity_probabilities(
    pulls_since_four_plus: int,
    pulls_since_five: int,
    configured: dict[int, float],
) -> dict[int, float]:
    five = five_star_probability(pulls_since_five, configured[5])
    if pulls_since_four_plus + 1 >= 10:
        return {1: 0.0, 2: 0.0, 3: 0.0, 4: 100.0 - five, 5: five}
    lower_total = sum(configured[rarity] for rarity in range(1, 5))
    remaining = 100.0 - five
    if lower_total <= 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "1~4성 확률 합계가 0입니다.")
    return {
        **{rarity: remaining * configured[rarity] / lower_total for rarity in range(1, 5)},
        5: five,
    }


def weighted_choice(items, weights, rng: random.Random):
    point = rng.random() * sum(weights)
    cursor = 0.0
    for item, weight in zip(items, weights):
        cursor += weight
        if point < cursor:
            return item
    return items[-1]


@dataclass(frozen=True)
class DrawResult:
    history: DrawHistory
    card: Card
    four_remaining: int
    five_remaining: int
    draws_remaining: int
    daily_remaining: int
    bonus_tickets: int
    repeated: bool = False


@dataclass(frozen=True)
class DrawBatchResult:
    batch_id: str
    results: tuple[DrawResult, ...]
    four_remaining: int
    five_remaining: int
    draws_remaining: int
    daily_remaining: int
    bonus_tickets: int
    repeated: bool = False


def draw_counters(state: DrawState | None) -> tuple[int, int]:
    """Return usable counters even before a user's draw-state row exists."""
    if state is None:
        return 0, 0
    return int(state.pulls_since_four_plus or 0), int(state.pulls_since_five or 0)


def daily_draw_limit(db: Session) -> int:
    setting = db.get(DrawSetting, 1)
    return int(setting.daily_draws) if setting is not None else 1


def draw_ticket_status(db: Session, user_id: int, now: datetime | None = None) -> dict[str, int | bool]:
    draw_day = logical_draw_day(now)
    daily_used = int(
        db.scalar(
            select(func.count(DrawHistory.id)).where(
                DrawHistory.user_id == user_id,
                DrawHistory.draw_day == draw_day,
                DrawHistory.ticket_source == "daily",
            )
        )
        or 0
    )
    allowance = db.get(DailyDrawAllowance, (user_id, draw_day))
    daily_total = daily_draw_limit(db) + (int(allowance.extra_draws) if allowance else 0)
    daily_remaining = max(0, daily_total - daily_used)
    wallet = db.get(DrawWallet, user_id)
    bonus_tickets = int(wallet.bonus_tickets) if wallet else 0
    draws_remaining = daily_remaining + bonus_tickets
    return {
        "eligible": draws_remaining > 0,
        "draws_remaining": draws_remaining,
        "daily_remaining": daily_remaining,
        "bonus_tickets": bonus_tickets,
    }


def perform_draw_batch(
    db: Session,
    user_id: int,
    idempotency_key: str,
    *,
    count: int,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> DrawBatchResult:
    if count not in {1, 10}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "뽑기 수는 1회 또는 10회여야 합니다.")
    now = now or utcnow()
    rng = rng or random.SystemRandom()
    db.scalar(select(User).where(User.id == user_id).with_for_update())
    existing_batch = db.scalar(select(DrawBatch).where(DrawBatch.user_id == user_id, DrawBatch.idempotency_key == idempotency_key))
    histories: list[DrawHistory] = []
    batch_id = existing_batch.id if existing_batch else ""
    if existing_batch:
        if existing_batch.requested_count != count:
            raise HTTPException(status.HTTP_409_CONFLICT, "같은 요청 키가 다른 뽑기 수에 사용되었습니다.")
        histories = db.scalars(select(DrawHistory).where(DrawHistory.batch_id == existing_batch.id).order_by(DrawHistory.batch_position)).all()
    elif count == 1:
        legacy = db.scalar(select(DrawHistory).where(DrawHistory.user_id == user_id, DrawHistory.idempotency_key == idempotency_key))
        if legacy:
            histories = [legacy]
            batch_id = legacy.id
    if histories:
        four_count, five_count = draw_counters(db.get(DrawState, user_id))
        tickets = draw_ticket_status(db, user_id, now)
        repeated_results = []
        for history in histories:
            card = db.get(Card, history.card_id) if history.card_id else None
            if card is None:
                raise HTTPException(status.HTTP_410_GONE, "이전에 뽑은 카드가 삭제되었습니다.")
            repeated_results.append(DrawResult(history, card, 10 - four_count, 90 - five_count, int(tickets["draws_remaining"]), int(tickets["daily_remaining"]), int(tickets["bonus_tickets"]), True))
        return DrawBatchResult(
            batch_id, tuple(repeated_results), 10 - four_count, 90 - five_count,
            int(tickets["draws_remaining"]), int(tickets["daily_remaining"]), int(tickets["bonus_tickets"]), True,
        )

    draw_day = logical_draw_day(now)
    tickets = draw_ticket_status(db, user_id, now)
    if int(tickets["draws_remaining"]) < count:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{count}회 뽑기에 필요한 뽑기권이 부족합니다.")
    daily_remaining = int(tickets["daily_remaining"])
    bonus_needed = max(0, count - daily_remaining)
    wallet = db.scalar(select(DrawWallet).where(DrawWallet.user_id == user_id).with_for_update())
    if bonus_needed:
        if wallet is None or wallet.bonus_tickets < bonus_needed:
            raise HTTPException(status.HTTP_409_CONFLICT, "사용 가능한 추가 뽑기권이 부족합니다.")
        wallet.bonus_tickets -= bonus_needed

    state = db.scalar(select(DrawState).where(DrawState.user_id == user_id).with_for_update())
    if state is None:
        state = DrawState(user_id=user_id, pulls_since_four_plus=0, pulls_since_five=0)
        db.add(state)
        db.flush()
    batch = DrawBatch(user_id=user_id, requested_count=count, idempotency_key=idempotency_key, created_at=now)
    db.add(batch)
    db.flush()
    configured = base_probabilities(db)
    results: list[tuple[DrawHistory, Card]] = []
    for position in range(count):
        rarity_chances = rarity_probabilities(state.pulls_since_four_plus, state.pulls_since_five, configured)
        rarities = [1, 2, 3, 4, 5]
        rarity = weighted_choice(rarities, [rarity_chances[item] for item in rarities], rng)
        cards = db.scalars(select(Card).where(Card.active.is_(True), Card.rarity == rarity).order_by(Card.id)).all()
        if not cards:
            raise HTTPException(status.HTTP_409_CONFLICT, f"활성 {rarity}성 카드가 없습니다.")
        card = weighted_choice(cards, [float(item.weight) if item.weight is not None else 1.0 for item in cards], rng)
        inventory = db.scalar(select(Inventory).where(Inventory.user_id == user_id, Inventory.card_id == card.id).with_for_update())
        if inventory is None:
            inventory = Inventory(user_id=user_id, card_id=card.id, quantity=0)
            db.add(inventory)
        inventory.quantity += 1
        unlock_card(db, user_id, card.id)
        if rarity == 5:
            state.pulls_since_four_plus = 0
            state.pulls_since_five = 0
        elif rarity == 4:
            state.pulls_since_four_plus = 0
            state.pulls_since_five += 1
        else:
            state.pulls_since_four_plus += 1
            state.pulls_since_five += 1
        ticket_source = "daily" if position < daily_remaining else "bonus"
        history = DrawHistory(user_id=user_id, card_id=card.id, card_name=card.name, card_rarity=card.rarity, card_yp=card.yp, draw_day=draw_day, ticket_source=ticket_source, idempotency_key=idempotency_key if count == 1 else f"{batch.id}:{position}", batch_id=batch.id, batch_position=position, drawn_at=now)
        db.add(history)
        db.flush()
        if rarity == 5:
            db.add(FiveStarEvent(draw_id=history.id, user_id=user_id, card_id=card.id, created_at=now))
        results.append((history, card))
    db.commit()
    tickets = draw_ticket_status(db, user_id, now)
    four_remaining = 10 - state.pulls_since_four_plus
    five_remaining = 90 - state.pulls_since_five
    draw_results = tuple(DrawResult(history, card, four_remaining, five_remaining, int(tickets["draws_remaining"]), int(tickets["daily_remaining"]), int(tickets["bonus_tickets"])) for history, card in results)
    return DrawBatchResult(
        batch.id, draw_results, four_remaining, five_remaining,
        int(tickets["draws_remaining"]), int(tickets["daily_remaining"]), int(tickets["bonus_tickets"]),
    )


def perform_draw(
    db: Session,
    user_id: int,
    idempotency_key: str,
    *,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> DrawResult:
    return perform_draw_batch(db, user_id, idempotency_key, count=1, now=now, rng=rng).results[0]


def collection_yp(db: Session, user_id: int) -> int:
    return effective_yp(db, user_id).total_yp


def user_probability_view(db: Session, user_id: int) -> dict:
    four_count, five_count = draw_counters(db.get(DrawState, user_id))
    rarity_chances = rarity_probabilities(
        four_count,
        five_count,
        base_probabilities(db),
    )
    cards = db.scalars(select(Card).where(Card.active.is_(True)).order_by(Card.rarity, Card.name)).all()
    by_rarity: dict[int, list[Card]] = {rarity: [] for rarity in range(1, 6)}
    for card in cards:
        by_rarity[card.rarity].append(card)
    card_values = []
    for rarity, rarity_cards in by_rarity.items():
        total = sum(float(card.weight) if card.weight is not None else 1.0 for card in rarity_cards)
        for card in rarity_cards:
            weight = float(card.weight) if card.weight is not None else 1.0
            card_values.append(
                {
                    "card_id": card.id,
                    "name": card.name,
                    "rarity": card.rarity,
                    "probability": rarity_chances[rarity] * weight / total if total else 0.0,
                }
            )
    return {
        "rarities": rarity_chances,
        "cards": card_values,
        "four_remaining": 10 - four_count,
        "five_remaining": 90 - five_count,
    }
