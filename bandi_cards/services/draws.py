from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Card, DrawHistory, DrawState, FiveStarEvent, Inventory, User, utcnow
from .probabilities import base_probabilities


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
    repeated: bool = False


def perform_draw(
    db: Session,
    user_id: int,
    idempotency_key: str,
    *,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> DrawResult:
    now = now or utcnow()
    rng = rng or random.SystemRandom()
    existing = db.scalar(
        select(DrawHistory).where(
            DrawHistory.user_id == user_id,
            DrawHistory.idempotency_key == idempotency_key,
        )
    )
    if existing:
        card = db.get(Card, existing.card_id) if existing.card_id else None
        if card is None:
            raise HTTPException(status.HTTP_410_GONE, "이전에 뽑은 카드가 삭제되었습니다.")
        state = db.get(DrawState, user_id) or DrawState(user_id=user_id)
        return DrawResult(existing, card, 10 - state.pulls_since_four_plus, 90 - state.pulls_since_five, True)

    db.scalar(select(User).where(User.id == user_id).with_for_update())
    draw_day = logical_draw_day(now)
    if db.scalar(select(DrawHistory.id).where(DrawHistory.user_id == user_id, DrawHistory.draw_day == draw_day)):
        raise HTTPException(status.HTTP_409_CONFLICT, "오늘의 뽑기를 이미 사용했습니다.")

    state = db.scalar(select(DrawState).where(DrawState.user_id == user_id).with_for_update())
    if state is None:
        state = DrawState(user_id=user_id)
        db.add(state)
        db.flush()

    rarity_chances = rarity_probabilities(
        state.pulls_since_four_plus,
        state.pulls_since_five,
        base_probabilities(db),
    )
    rarities = [1, 2, 3, 4, 5]
    rarity = weighted_choice(rarities, [rarity_chances[item] for item in rarities], rng)
    cards = db.scalars(select(Card).where(Card.active.is_(True), Card.rarity == rarity).order_by(Card.id)).all()
    if not cards:
        raise HTTPException(status.HTTP_409_CONFLICT, f"활성 {rarity}성 카드가 없습니다.")
    card = weighted_choice(cards, [float(item.weight) if item.weight is not None else 1.0 for item in cards], rng)

    inventory = db.scalar(
        select(Inventory).where(Inventory.user_id == user_id, Inventory.card_id == card.id).with_for_update()
    )
    if inventory is None:
        inventory = Inventory(user_id=user_id, card_id=card.id, quantity=0)
        db.add(inventory)
    inventory.quantity += 1

    if rarity == 5:
        state.pulls_since_four_plus = 0
        state.pulls_since_five = 0
    elif rarity == 4:
        state.pulls_since_four_plus = 0
        state.pulls_since_five += 1
    else:
        state.pulls_since_four_plus += 1
        state.pulls_since_five += 1

    history = DrawHistory(
        user_id=user_id,
        card_id=card.id,
        card_name=card.name,
        card_rarity=card.rarity,
        card_yp=card.yp,
        draw_day=draw_day,
        idempotency_key=idempotency_key,
        drawn_at=now,
    )
    db.add(history)
    db.flush()
    if rarity == 5:
        db.add(FiveStarEvent(draw_id=history.id, user_id=user_id, card_id=card.id, created_at=now))
    db.commit()
    return DrawResult(
        history,
        card,
        10 - state.pulls_since_four_plus,
        90 - state.pulls_since_five,
    )


def collection_yp(db: Session, user_id: int) -> int:
    value = db.scalar(
        select(func.coalesce(func.sum(Card.yp), 0))
        .select_from(Inventory)
        .join(Card, Card.id == Inventory.card_id)
        .where(Inventory.user_id == user_id, Inventory.quantity > 0)
    )
    return int(value or 0)


def user_probability_view(db: Session, user_id: int) -> dict:
    state = db.get(DrawState, user_id) or DrawState(user_id=user_id)
    rarity_chances = rarity_probabilities(
        state.pulls_since_four_plus,
        state.pulls_since_five,
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
        "four_remaining": 10 - state.pulls_since_four_plus,
        "five_remaining": 90 - state.pulls_since_five,
    }
