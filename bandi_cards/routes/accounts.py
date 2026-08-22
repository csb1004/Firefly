from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..security import AuthContext, require_csrf, require_ready_user
from ..services.discord_oauth import avatar_url


router = APIRouter(prefix="/api", tags=["accounts"])


def public_user(user: User) -> dict:
    return {
        "id": user.id,
        "discord_id": user.discord_id,
        "username": user.username,
        "display_name": user.global_name or user.username,
        "avatar_url": avatar_url(user.discord_id, user.avatar_hash),
        "accepts_gifts": user.accepts_gifts,
        "accepts_trades": user.accepts_trades,
    }


class SettingsBody(BaseModel):
    accepts_gifts: bool
    accepts_trades: bool


@router.post("/me/warning", status_code=204)
def acknowledge_warning(
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    context.user.warning_acknowledged = True
    db.add(context.user)
    db.commit()


@router.put("/me/settings")
def update_settings(
    body: SettingsBody,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict:
    if not context.user.warning_acknowledged:
        raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED, "첫 로그인 안내 확인이 필요합니다.")
    context.user.accepts_gifts = body.accepts_gifts
    context.user.accepts_trades = body.accepts_trades
    db.add(context.user)
    db.commit()
    return public_user(context.user)


@router.get("/users/search")
def search_users(
    q: str = Query(min_length=1, max_length=64),
    user: User = Depends(require_ready_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    normalized = q.strip().casefold()
    conditions = [
        func.lower(User.username).contains(normalized),
        func.lower(func.coalesce(User.global_name, "")).contains(normalized),
    ]
    if normalized.isdigit():
        conditions.append(User.discord_id == normalized)
    users = db.scalars(
        select(User).where(or_(*conditions)).order_by(User.username, User.discord_id).limit(20)
    ).all()
    return [public_user(item) for item in users]


@router.get("/users/{user_id}")
def get_user_profile(
    user_id: int,
    _: User = Depends(require_ready_user),
    db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "사용자를 찾을 수 없습니다.")
    return public_user(user)
