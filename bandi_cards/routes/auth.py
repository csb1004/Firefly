from __future__ import annotations

from datetime import timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import OAuthAttempt, User, WebSession, WebSocketTicket, as_utc, utcnow
from ..security import (
    ABSOLUTE_TIMEOUT,
    SESSION_COOKIE,
    AuthContext,
    get_auth_context,
    csrf_token_for_session,
    pkce_challenge,
    random_token,
    require_csrf,
    token_hash,
)
from ..services.discord_oauth import authorization_url, avatar_url, exchange_code


router = APIRouter(prefix="/api/auth", tags=["authentication"])


def user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "discord_id": user.discord_id,
        "username": user.username,
        "display_name": user.global_name or user.username,
        "avatar_url": avatar_url(user.discord_id, user.avatar_hash),
        "warning_acknowledged": user.warning_acknowledged,
        "accepts_gifts": user.accepts_gifts,
        "accepts_trades": user.accepts_trades,
        "is_admin": user.discord_id == str(settings.special_user_id),
    }


@router.get("/discord")
def discord_login(db: Session = Depends(get_db)):
    if not settings.discord_ready:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Discord OAuth 환경 변수가 필요합니다.")
    state = random_token()
    verifier = random_token(48)
    db.add(
        OAuthAttempt(
            state_hash=token_hash(state),
            verifier=verifier,
            expires_at=utcnow() + timedelta(minutes=10),
        )
    )
    db.commit()
    return RedirectResponse(authorization_url(state, pkce_challenge(verifier)))


@router.get("/discord/callback")
async def discord_callback(
    code: str = Query(min_length=1),
    state: str = Query(min_length=1),
    db: Session = Depends(get_db),
):
    attempt = db.get(OAuthAttempt, token_hash(state))
    if attempt is None or as_utc(attempt.expires_at) <= utcnow():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "유효하지 않거나 만료된 OAuth state입니다.")
    db.delete(attempt)
    db.commit()
    try:
        profile = await exchange_code(code, attempt.verifier)
    except (httpx.HTTPError, KeyError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Discord 인증을 완료하지 못했습니다.") from exc

    user = db.scalar(select(User).where(User.discord_id == profile.id))
    now = utcnow()
    if user is None:
        user = User(
            discord_id=profile.id,
            username=profile.username,
            global_name=profile.global_name,
            avatar_hash=profile.avatar,
            profile_synced_at=now,
            profile_sync_attempted_at=now,
        )
        db.add(user)
        db.flush()
    else:
        user.username = profile.username
        user.global_name = profile.global_name
        user.avatar_hash = profile.avatar
        user.profile_synced_at = now
        user.profile_sync_attempted_at = now
        user.profile_sync_error = None

    raw_session = random_token()
    db.add(
        WebSession(
            token_hash=token_hash(raw_session),
            user_id=user.id,
            expires_at=now + ABSOLUTE_TIMEOUT,
        )
    )
    db.commit()
    response = RedirectResponse("/" if user.warning_acknowledged else "/welcome")
    response.set_cookie(
        SESSION_COOKIE,
        raw_session,
        max_age=int(ABSOLUTE_TIMEOUT.total_seconds()),
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/me")
def me(context: AuthContext = Depends(get_auth_context)) -> dict:
    return user_payload(context.user)


@router.post("/csrf")
def csrf_token(context: AuthContext = Depends(get_auth_context)) -> dict:
    return {"csrf_token": csrf_token_for_session(context.session_token)}


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    db.delete(context.session)
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.post("/websocket-ticket")
def websocket_ticket(
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict:
    raw = random_token()
    db.add(
        WebSocketTicket(
            token_hash=token_hash(raw),
            user_id=context.user.id,
            expires_at=utcnow() + timedelta(seconds=60),
        )
    )
    db.commit()
    return {"ticket": raw, "expires_in": 60}
