from __future__ import annotations

from collections import defaultdict

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Card, RaritySetting


def base_probabilities(db: Session) -> dict[int, float]:
    return {row.rarity: float(row.probability) for row in db.scalars(select(RaritySetting)).all()}


def validate_probability_configuration(db: Session, values: dict[int, float]) -> None:
    if set(values) != {1, 2, 3, 4, 5}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "1~5성 확률이 모두 필요합니다.")
    if any(value < 0 or value > 100 for value in values.values()):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "확률은 0~100 범위여야 합니다.")
    if abs(sum(values.values()) - 100.0) > 0.0001:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "등급 확률 합계는 100%여야 합니다.")
    active_rarities = set(db.scalars(select(Card.rarity).where(Card.active.is_(True))).all())
    missing = [rarity for rarity, probability in values.items() if probability > 0 and rarity not in active_rarities]
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"활성 카드가 없는 등급에는 확률을 줄 수 없습니다: {missing}",
        )


def card_probabilities(db: Session, rarity_values: dict[int, float] | None = None) -> list[dict]:
    rarity_values = rarity_values or base_probabilities(db)
    cards = db.scalars(select(Card).where(Card.active.is_(True)).order_by(Card.rarity, Card.name)).all()
    grouped: dict[int, list[Card]] = defaultdict(list)
    for card in cards:
        grouped[card.rarity].append(card)
    result = []
    for rarity, rarity_cards in grouped.items():
        weights = [float(card.weight) if card.weight is not None else 1.0 for card in rarity_cards]
        total_weight = sum(weights)
        for card, weight in zip(rarity_cards, weights):
            result.append(
                {
                    "card_id": card.id,
                    "name": card.name,
                    "rarity": card.rarity,
                    "probability": rarity_values.get(rarity, 0.0) * weight / total_weight,
                }
            )
    return result
