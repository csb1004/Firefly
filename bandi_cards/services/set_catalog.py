from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Card, CardSet, CardSetMember, Inventory, SetEffect, SetEffectBonusTargetCard, SetEffectTargetCard
from .set_effects import effective_yp


def user_set_definitions(db: Session, user_id: int) -> list[dict]:
    card_sets = db.scalars(
        select(CardSet).where(CardSet.active.is_(True)).order_by(CardSet.name)
    ).all()
    if not card_sets:
        return []

    set_ids = [card_set.id for card_set in card_sets]
    member_rows = db.execute(
        select(CardSetMember, Card)
        .join(Card, Card.id == CardSetMember.card_id)
        .where(CardSetMember.set_id.in_(set_ids))
        .order_by(CardSetMember.set_id, Card.rarity.desc(), Card.name)
    ).all()
    effects = db.scalars(
        select(SetEffect)
        .where(SetEffect.set_id.in_(set_ids))
        .order_by(SetEffect.set_id, SetEffect.position, SetEffect.id)
    ).all()
    effect_ids = [effect.id for effect in effects]
    target_rows = db.execute(
        select(SetEffectTargetCard, Card)
        .join(Card, Card.id == SetEffectTargetCard.card_id)
        .where(SetEffectTargetCard.effect_id.in_(effect_ids))
        .order_by(SetEffectTargetCard.effect_id, Card.rarity.desc(), Card.name)
    ).all() if effect_ids else []
    bonus_target_rows = db.execute(
        select(SetEffectBonusTargetCard, Card)
        .join(Card, Card.id == SetEffectBonusTargetCard.card_id)
        .where(SetEffectBonusTargetCard.effect_id.in_(effect_ids))
        .order_by(SetEffectBonusTargetCard.effect_id, Card.rarity.desc(), Card.name)
    ).all() if effect_ids else []
    owned_ids = set(db.scalars(
        select(Inventory.card_id).where(Inventory.user_id == user_id, Inventory.quantity > 0)
    ).all())
    yp = effective_yp(db, user_id)
    bonuses_by_set = {bonus.set_id: bonus for bonus in yp.set_bonuses}

    members_by_set: dict[str, list[dict]] = {set_id: [] for set_id in set_ids}
    for member, card in member_rows:
        members_by_set[member.set_id].append({"id": card.id, "name": card.name, "rarity": card.rarity})
    effects_by_set: dict[str, list[SetEffect]] = {set_id: [] for set_id in set_ids}
    for effect in effects:
        effects_by_set[effect.set_id].append(effect)
    targets_by_effect: dict[str, list[dict]] = {effect_id: [] for effect_id in effect_ids}
    bonus_targets_by_effect: dict[str, list[dict]] = {effect_id: [] for effect_id in effect_ids}
    for target, card in target_rows:
        targets_by_effect[target.effect_id].append({"id": card.id, "name": card.name, "rarity": card.rarity})
    for target, card in bonus_target_rows:
        bonus_targets_by_effect[target.effect_id].append({"id": card.id, "name": card.name, "rarity": card.rarity})

    result = []
    for card_set in card_sets:
        members = members_by_set[card_set.id]
        owned_count = sum(member["id"] in owned_ids for member in members)
        set_bonus = bonuses_by_set.get(card_set.id)
        result.append({
            "id": card_set.id,
            "name": card_set.name,
            "completed": bool(members) and owned_count == len(members),
            "owned_member_count": owned_count,
            "required_member_count": len(members),
            "member_cards": members,
            "effects": [{
                "id": effect.id,
                "target_scope": effect.target_scope,
                "target_rarity": effect.target_rarity,
                "target_cards": targets_by_effect[effect.id],
                "bonus_target_scope": effect.bonus_target_scope if effect.bonus_target_scope is not None else effect.target_scope,
                "bonus_target_rarity": effect.bonus_target_rarity if effect.bonus_target_scope is not None else effect.target_rarity,
                "bonus_target_cards": bonus_targets_by_effect[effect.id] if effect.bonus_target_scope is not None else targets_by_effect[effect.id],
                "count_mode": effect.count_mode,
                "bonus_type": effect.bonus_type,
                "value": float(effect.value),
                "max_count": effect.max_count,
            } for effect in effects_by_set[card_set.id]],
            "yp_bonus": {
                "total": float(set_bonus.total_bonus) if set_bonus else 0.0,
                "cards": [{
                    "card_id": card.card_id,
                    "card_name": card.card_name,
                    "rarity": card.rarity,
                    "quantity": card.quantity,
                    "base_yp": card.base_yp,
                    "fixed_bonus": float(card.fixed_bonus),
                    "percent_bonus": float(card.percent_bonus),
                    "total_bonus": float(card.total_bonus),
                } for card in set_bonus.cards] if set_bonus else [],
            },
        })
    return result
