from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Card, CardSet, CardSetMember, Inventory, SetEffect, SetEffectTargetCard


@dataclass(frozen=True)
class YPBreakdown:
    base_yp: int
    fixed_bonus: Decimal
    percent_bonus: Decimal
    total_yp: int
    active_sets: tuple[str, ...]


def _evaluate(
    owned: dict[str, tuple[Card, int]],
    sets: list[CardSet],
    members: dict[str, set[str]],
    effects: dict[str, list[SetEffect]],
    targets: dict[str, set[str]],
) -> YPBreakdown:
    base = sum(card.yp * quantity for card, quantity in owned.values() if quantity > 0)
    fixed = Decimal(0)
    percent = Decimal(0)
    active_names: list[str] = []
    owned_ids = {card_id for card_id, (_card, quantity) in owned.items() if quantity > 0}
    for card_set in sets:
        required = members.get(card_set.id, set())
        if not required or not required.issubset(owned_ids):
            continue
        active_names.append(card_set.name)
        for effect in effects.get(card_set.id, []):
            if effect.target_scope == "set_members":
                candidate_ids = required
            elif effect.target_scope == "selected_cards":
                candidate_ids = targets.get(effect.id, set())
            elif effect.target_scope == "rarity":
                candidate_ids = {
                    card_id for card_id, (card, quantity) in owned.items()
                    if quantity > 0 and card.rarity == effect.target_rarity
                }
            else:
                candidate_ids = owned_ids
            qualifying = [owned[card_id] for card_id in candidate_ids if card_id in owned and owned[card_id][1] > 0]
            if effect.count_mode == "once":
                count = 1 if qualifying else 0
            elif effect.count_mode == "distinct":
                count = len(qualifying)
            else:
                count = sum(quantity for _card, quantity in qualifying)
            if effect.max_count is not None:
                count = min(count, effect.max_count)
            amount = Decimal(effect.value) * count
            if effect.bonus_type == "fixed":
                fixed += amount
            else:
                percent += amount
    total = ((Decimal(base) + fixed) * (Decimal(1) + percent / Decimal(100))).to_integral_value(
        rounding=ROUND_FLOOR
    )
    return YPBreakdown(base, fixed, percent, int(total), tuple(active_names))


def effective_yp_many(
    db: Session,
    user_ids: list[int],
    *,
    quantity_overrides: dict[int, dict[str, int]] | None = None,
) -> dict[int, YPBreakdown]:
    if not user_ids:
        return {}
    rows = db.execute(
        select(Inventory, Card)
        .join(Card, Card.id == Inventory.card_id)
        .where(Inventory.user_id.in_(user_ids), Inventory.quantity > 0)
    ).all()
    owned_by_user: dict[int, dict[str, tuple[Card, int]]] = {user_id: {} for user_id in user_ids}
    for inventory, card in rows:
        quantity = (quantity_overrides or {}).get(inventory.user_id, {}).get(card.id, inventory.quantity)
        if quantity > 0:
            owned_by_user[inventory.user_id][card.id] = (card, quantity)
    override_card_ids = {
        card_id
        for overrides in (quantity_overrides or {}).values()
        for card_id, quantity in overrides.items()
        if quantity > 0
    }
    override_cards = {
        card.id: card for card in db.scalars(select(Card).where(Card.id.in_(override_card_ids))).all()
    } if override_card_ids else {}
    for user_id, overrides in (quantity_overrides or {}).items():
        for card_id, quantity in overrides.items():
            if quantity > 0 and card_id in override_cards:
                owned_by_user.setdefault(user_id, {})[card_id] = (override_cards[card_id], quantity)
            elif quantity <= 0:
                owned_by_user.setdefault(user_id, {}).pop(card_id, None)
    sets = db.scalars(select(CardSet).where(CardSet.active.is_(True)).order_by(CardSet.name)).all()
    set_ids = [item.id for item in sets]
    members: dict[str, set[str]] = {set_id: set() for set_id in set_ids}
    effects: dict[str, list[SetEffect]] = {set_id: [] for set_id in set_ids}
    targets: dict[str, set[str]] = {}
    if set_ids:
        for member in db.scalars(select(CardSetMember).where(CardSetMember.set_id.in_(set_ids))).all():
            members[member.set_id].add(member.card_id)
        all_effects = db.scalars(
            select(SetEffect).where(SetEffect.set_id.in_(set_ids)).order_by(SetEffect.set_id, SetEffect.position, SetEffect.id)
        ).all()
        for effect in all_effects:
            effects[effect.set_id].append(effect)
            targets[effect.id] = set()
        if all_effects:
            for target in db.scalars(
                select(SetEffectTargetCard).where(SetEffectTargetCard.effect_id.in_([effect.id for effect in all_effects]))
            ).all():
                targets[target.effect_id].add(target.card_id)
    return {
        user_id: _evaluate(owned_by_user[user_id], sets, members, effects, targets)
        for user_id in user_ids
    }


def effective_yp(
    db: Session,
    user_id: int,
    *,
    quantity_overrides: dict[str, int] | None = None,
) -> YPBreakdown:
    return effective_yp_many(
        db,
        [user_id],
        quantity_overrides={user_id: quantity_overrides or {}},
    )[user_id]
