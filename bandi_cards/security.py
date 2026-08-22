from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User, WebSession, as_utc, utcnow


SESSION_COOKIE = "bandi_session"
IDLE_TIMEOUT = timedelta(days=30)
ABSOLUTE_TIMEOUT = timedelta(days=90)


def random_token(bytes_count: int = 32) -> str:
    return secrets.token_urlsafe(bytes_count)


def token_hash(value: str) -> str:
    return hmac.new(settings.session_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


@dataclass
class AuthContext:
    user: User
    session: WebSession
    session_token: str


def csrf_token_for_session(session_token: str) -> str:
    return hmac.new(
        settings.session_secret.encode(),
        f"csrf:{session_token}".encode(),
        hashlib.sha256,
    ).hexdigest()


def get_auth_context(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    db: Session = Depends(get_db),
) -> AuthContext:
    if not session_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "로그인이 필요합니다.")
    session = db.get(WebSession, token_hash(session_token))
    now = utcnow()
    if (
        session is None
        or as_utc(session.expires_at) <= now
        or as_utc(session.last_seen_at) + IDLE_TIMEOUT <= now
    ):
        if session is not None:
            db.delete(session)
            db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "세션이 만료되었습니다.")
    user = db.get(User, session.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "계정을 찾을 수 없습니다.")
    session.last_seen_at = now
    db.commit()
    return AuthContext(user=user, session=session, session_token=session_token)


def require_user(context: AuthContext = Depends(get_auth_context)) -> User:
    return context.user


def require_ready_user(user: User = Depends(require_user)) -> User:
    if not user.warning_acknowledged:
        raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED, "첫 로그인 안내 확인이 필요합니다.")
    return user


def require_admin(user: User = Depends(require_ready_user)) -> User:
    if user.discord_id != str(settings.special_user_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "관리자만 사용할 수 있습니다.")
    return user


def require_csrf(
    context: AuthContext = Depends(get_auth_context),
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> AuthContext:
    expected = csrf_token_for_session(context.session_token)
    if not csrf_token or not hmac.compare_digest(csrf_token, expected):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF 검증에 실패했습니다.")
    return context


def require_csrf_user(context: AuthContext = Depends(require_csrf)) -> User:
    if not context.user.warning_acknowledged:
        raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED, "첫 로그인 안내 확인이 필요합니다.")
    return context.user


def require_admin_csrf(context: AuthContext = Depends(require_csrf)) -> User:
    if not context.user.warning_acknowledged:
        raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED, "첫 로그인 안내 확인이 필요합니다.")
    if context.user.discord_id != str(settings.special_user_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "관리자만 사용할 수 있습니다.")
    return context.user
