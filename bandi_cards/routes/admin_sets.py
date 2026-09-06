from __future__ import annotations

import json
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AdminAudit, Card, CardSet, CardSetMember, SetEffect, SetEffectBonusTargetCard, SetEffectTargetCard, User
from ..season_reset import track_season_mutation
from ..security import require_admin, require_admin_csrf


router = APIRouter(prefix="/api/admin/sets", tags=["set administration"])


class EffectBody(BaseModel):
    target_scope: str
    target_rarity: int | None = Field(default=None, ge=1, le=5)
    target_card_ids: list[str] = Field(default_factory=list)
    bonus_target_scope: str | None = None
    bonus_target_rarity: int | None = Field(default=None, ge=1, le=5)
    bonus_target_card_ids: list[str] = Field(default_factory=list)
    count_mode: str
    bonus_type: str
    value: Decimal = Field(ge=0)
    max_count: int | None = Field(default=None, ge=1)


class SetBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    active: bool = True
    member_card_ids: list[str] = Field(min_length=1)
    effects: list[EffectBody] = Field(min_length=1)


def resolve_rarity(scope: str, rarity: int | None) -> int | None:
    return (rarity if rarity is not None else 1) if scope == "rarity" else None


def serialize_set(db: Session, card_set: CardSet) -> dict:
    member_ids = db.scalars(select(CardSetMember.card_id).where(CardSetMember.set_id == card_set.id).order_by(CardSetMember.card_id)).all()
    effects = db.scalars(select(SetEffect).where(SetEffect.set_id == card_set.id).order_by(SetEffect.position, SetEffect.id)).all()
    target_rows = db.execute(select(SetEffectTargetCard.effect_id, SetEffectTargetCard.card_id).where(SetEffectTargetCard.effect_id.in_([effect.id for effect in effects]))).all() if effects else []
    bonus_target_rows = db.execute(select(SetEffectBonusTargetCard.effect_id, SetEffectBonusTargetCard.card_id).where(SetEffectBonusTargetCard.effect_id.in_([effect.id for effect in effects]))).all() if effects else []
    targets: dict[str, list[str]] = {effect.id: [] for effect in effects}
    bonus_targets: dict[str, list[str]] = {effect.id: [] for effect in effects}
    for effect_id, card_id in target_rows:
        targets[effect_id].append(card_id)
    for effect_id, card_id in bonus_target_rows:
        bonus_targets[effect_id].append(card_id)
    return {
        "id": card_set.id,
        "name": card_set.name,
        "active": card_set.active,
        "member_card_ids": list(member_ids),
        "effects": [{
            "id": effect.id,
            "target_scope": effect.target_scope,
            "target_rarity": effect.target_rarity,
            "target_card_ids": targets[effect.id],
            "bonus_target_scope": effect.bonus_target_scope if effect.bonus_target_scope is not None else effect.target_scope,
            "bonus_target_rarity": effect.bonus_target_rarity if effect.bonus_target_scope is not None else effect.target_rarity,
            "bonus_target_card_ids": bonus_targets[effect.id] if effect.bonus_target_scope is not None else targets[effect.id],
            "count_mode": effect.count_mode,
            "bonus_type": effect.bonus_type,
            "value": float(effect.value),
            "max_count": effect.max_count,
        } for effect in effects],
    }


def validate_body(db: Session, body: SetBody, *, exclude_id: str | None = None) -> None:
    if len(set(body.member_card_ids)) != len(body.member_card_ids):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "세트 구성 카드가 중복되었습니다.")
    all_ids = set(body.member_card_ids)
    for effect in body.effects:
        bonus_scope = effect.bonus_target_scope if effect.bonus_target_scope is not None else effect.target_scope
        bonus_card_ids = effect.bonus_target_card_ids if effect.bonus_target_scope is not None else effect.target_card_ids
        count_card_ids = effect.target_card_ids if effect.target_scope == "selected_cards" else []
        resolved_bonus_card_ids = bonus_card_ids if bonus_scope == "selected_cards" else []
        if effect.target_scope not in {"set_members", "selected_cards", "rarity", "collection"}:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "지원하지 않는 적용 횟수 대상입니다.")
        if bonus_scope not in {"set_members", "selected_cards", "rarity", "collection"}:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "지원하지 않는 YP 증가 대상입니다.")
        if effect.count_mode not in {"once", "distinct", "quantity"} or effect.bonus_type not in {"fixed", "percent"}:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "지원하지 않는 효과 계산 방식입니다.")
        if effect.target_scope == "selected_cards" and not effect.target_card_ids:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "적용 횟수를 계산할 카드를 선택하세요.")
        if len(count_card_ids) != len(set(count_card_ids)):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "적용 횟수 대상 카드가 중복되었습니다.")
        if bonus_scope == "selected_cards" and not bonus_card_ids:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "YP가 증가할 카드를 선택하세요.")
        if len(resolved_bonus_card_ids) != len(set(resolved_bonus_card_ids)):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "YP 증가 대상 카드가 중복되었습니다.")
        if effect.bonus_type == "fixed" and effect.value != effect.value.to_integral_value():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "고정 YP는 정수여야 합니다.")
        all_ids.update(count_card_ids)
        all_ids.update(resolved_bonus_card_ids)
    existing_ids = set(db.scalars(select(Card.id).where(Card.id.in_(all_ids))).all())
    if existing_ids != all_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "존재하지 않는 카드가 포함되어 있습니다.")
    duplicate = db.scalar(select(CardSet.id).where(func.lower(CardSet.name) == body.name.strip().lower(), CardSet.id != exclude_id))
    if duplicate:
        raise HTTPException(status.HTTP_409_CONFLICT, "같은 이름의 세트가 이미 있습니다.")


def replace_set(db: Session, card_set: CardSet, body: SetBody) -> None:
    db.execute(delete(CardSetMember).where(CardSetMember.set_id == card_set.id))
    old_effect_ids = db.scalars(select(SetEffect.id).where(SetEffect.set_id == card_set.id)).all()
    if old_effect_ids:
        db.execute(delete(SetEffectTargetCard).where(SetEffectTargetCard.effect_id.in_(old_effect_ids)))
        db.execute(delete(SetEffectBonusTargetCard).where(SetEffectBonusTargetCard.effect_id.in_(old_effect_ids)))
    db.execute(delete(SetEffect).where(SetEffect.set_id == card_set.id))
    db.flush()
    card_set.name = body.name.strip()
    card_set.active = body.active
    db.add_all([CardSetMember(set_id=card_set.id, card_id=card_id) for card_id in body.member_card_ids])
    for position, item in enumerate(body.effects):
        bonus_scope = item.bonus_target_scope if item.bonus_target_scope is not None else item.target_scope
        target_rarity = resolve_rarity(item.target_scope, item.target_rarity)
        bonus_rarity = resolve_rarity(
            bonus_scope,
            item.bonus_target_rarity if item.bonus_target_scope is not None else item.target_rarity,
        )
        bonus_card_ids = item.bonus_target_card_ids if item.bonus_target_scope is not None else item.target_card_ids
        effect = SetEffect(set_id=card_set.id, target_scope=item.target_scope, target_rarity=target_rarity, bonus_target_scope=bonus_scope, bonus_target_rarity=bonus_rarity, count_mode=item.count_mode, bonus_type=item.bonus_type, value=item.value, max_count=item.max_count, position=position)
        db.add(effect)
        db.flush()
        if item.target_scope == "selected_cards":
            db.add_all([SetEffectTargetCard(effect_id=effect.id, card_id=card_id) for card_id in item.target_card_ids])
        if bonus_scope == "selected_cards":
            db.add_all([SetEffectBonusTargetCard(effect_id=effect.id, card_id=card_id) for card_id in bonus_card_ids])


@router.get("")
def list_sets(_: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[dict]:
    return [serialize_set(db, item) for item in db.scalars(select(CardSet).order_by(CardSet.name)).all()]


@router.post("", status_code=201)
def create_set(
    body: SetBody,
    admin: User = Depends(require_admin_csrf),
    _reset_guard: None = Depends(track_season_mutation),
    db: Session = Depends(get_db),
) -> dict:
    validate_body(db, body)
    card_set = CardSet(name=body.name.strip(), active=body.active)
    db.add(card_set)
    db.flush()
    replace_set(db, card_set, body)
    db.add(AdminAudit(admin_id=admin.id, action="set.create", target_type="card_set", target_id=card_set.id, details_json=json.dumps(body.model_dump(), default=str, ensure_ascii=False)))
    db.commit()
    return serialize_set(db, card_set)


@router.put("/{set_id}")
def update_set(
    set_id: str,
    body: SetBody,
    admin: User = Depends(require_admin_csrf),
    _reset_guard: None = Depends(track_season_mutation),
    db: Session = Depends(get_db),
) -> dict:
    card_set = db.scalar(select(CardSet).where(CardSet.id == set_id).with_for_update())
    if card_set is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "세트를 찾을 수 없습니다.")
    validate_body(db, body, exclude_id=set_id)
    replace_set(db, card_set, body)
    db.add(AdminAudit(admin_id=admin.id, action="set.update", target_type="card_set", target_id=set_id, details_json=json.dumps(body.model_dump(), default=str, ensure_ascii=False)))
    db.commit()
    return serialize_set(db, card_set)


@router.delete("/{set_id}", status_code=204)
def delete_set(
    set_id: str,
    admin: User = Depends(require_admin_csrf),
    _reset_guard: None = Depends(track_season_mutation),
    db: Session = Depends(get_db),
):
    card_set = db.get(CardSet, set_id)
    if card_set is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "세트를 찾을 수 없습니다.")
    db.add(AdminAudit(admin_id=admin.id, action="set.delete", target_type="card_set", target_id=set_id, details_json=json.dumps({"name": card_set.name}, ensure_ascii=False)))
    db.delete(card_set)
    db.commit()
