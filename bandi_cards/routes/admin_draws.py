from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AdminAudit, DailyDrawAllowance, DrawHistory, DrawSetting, DrawWallet, User
from ..security import require_admin, require_admin_csrf
from ..services.draws import daily_draw_limit, draw_ticket_status, logical_draw_day
from .accounts import public_user


router = APIRouter(prefix="/api/admin", tags=["draw administration"])


class DailyDrawsBody(BaseModel):
    daily_draws: int = Field(ge=0, le=100)


class GrantTicketsBody(BaseModel):
    amount: int = Field(ge=1, le=10_000)


def ticket_view(db: Session, user: User) -> dict:
    return {"user": public_user(user), **draw_ticket_status(db, user.id)}


@router.get("/draw-settings")
def get_draw_settings(_: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    return {"daily_draws": daily_draw_limit(db)}


@router.put("/draw-settings")
def update_draw_settings(
    body: DailyDrawsBody,
    admin: User = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> dict:
    setting = db.scalar(select(DrawSetting).where(DrawSetting.id == 1).with_for_update())
    before = daily_draw_limit(db)
    if setting is None:
        setting = DrawSetting(id=1, daily_draws=body.daily_draws)
        db.add(setting)
    else:
        setting.daily_draws = body.daily_draws
    db.add(
        AdminAudit(
            admin_id=admin.id,
            action="draw.daily_limit.update",
            target_type="draw_setting",
            target_id="1",
            details_json=json.dumps({"before": before, "after": body.daily_draws}),
        )
    )
    db.commit()
    return {"daily_draws": body.daily_draws}


@router.get("/users/{user_id}/draw-tickets")
def get_user_draw_tickets(
    user_id: int,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "사용자를 찾을 수 없습니다.")
    return ticket_view(db, user)


@router.post("/users/{user_id}/draw-tickets/grant")
def grant_draw_tickets(
    user_id: int,
    body: GrantTicketsBody,
    admin: User = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> dict:
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "사용자를 찾을 수 없습니다.")
    wallet = db.scalar(select(DrawWallet).where(DrawWallet.user_id == user_id).with_for_update())
    if wallet is None:
        wallet = DrawWallet(user_id=user_id, bonus_tickets=0)
        db.add(wallet)
    wallet.bonus_tickets += body.amount
    db.add(
        AdminAudit(
            admin_id=admin.id,
            action="draw.tickets.grant",
            target_type="user",
            target_id=str(user_id),
            details_json=json.dumps({"amount": body.amount, "balance": wallet.bonus_tickets}),
        )
    )
    db.commit()
    return ticket_view(db, user)


@router.post("/users/{user_id}/draw-tickets/reset-today")
def reset_user_draws_today(
    user_id: int,
    admin: User = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
) -> dict:
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "사용자를 찾을 수 없습니다.")
    draw_day = logical_draw_day()
    used_today = int(
        db.scalar(
            select(func.count(DrawHistory.id)).where(
                DrawHistory.user_id == user_id,
                DrawHistory.draw_day == draw_day,
            )
        )
        or 0
    )
    allowance = db.scalar(
        select(DailyDrawAllowance)
        .where(DailyDrawAllowance.user_id == user_id, DailyDrawAllowance.draw_day == draw_day)
        .with_for_update()
    )
    if allowance is None:
        allowance = DailyDrawAllowance(user_id=user_id, draw_day=draw_day, extra_draws=0)
        db.add(allowance)
    previous_extra = allowance.extra_draws
    allowance.extra_draws = max(previous_extra, used_today)
    restored = allowance.extra_draws - previous_extra
    db.add(
        AdminAudit(
            admin_id=admin.id,
            action="draw.daily_usage.reset",
            target_type="user",
            target_id=str(user_id),
            details_json=json.dumps({"draw_day": draw_day.isoformat(), "restored": restored}),
        )
    )
    db.commit()
    return {**ticket_view(db, user), "restored": restored}
