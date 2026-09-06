from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..realtime.connection_manager import manager
from ..season_reset import SeasonResetAlreadyRunning
from ..security import require_admin, require_admin_csrf
from ..services.season_reset import (
    CONFIRMATION_TEXT,
    SeasonResetConfigurationInvalid,
    SeasonResetLockUnavailable,
    execute_season_reset,
    preview_season_reset,
)


router = APIRouter(prefix="/api/admin/season-reset", tags=["admin season reset"])
logger = logging.getLogger(__name__)
RESET_BROADCAST_TIMEOUT_SECONDS = 3.0


class SeasonResetBody(BaseModel):
    confirmation: str


def _commit_reset(factory, admin_id: int) -> dict:
    with factory() as db:
        try:
            result = execute_season_reset(db, admin_id)
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise


async def _complete_reset_transaction(factory, admin_id: int) -> dict:
    operation = asyncio.create_task(asyncio.to_thread(_commit_reset, factory, admin_id))
    while not operation.done():
        try:
            await asyncio.shield(operation)
        except asyncio.CancelledError:
            continue
    return operation.result()


@router.get("/preview")
def preview_reset(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return preview_season_reset(db)
    except SeasonResetConfigurationInvalid as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.post("")
async def reset_season(
    body: SeasonResetBody,
    request: Request,
    admin: User = Depends(require_admin_csrf),
) -> dict:
    if body.confirmation != CONFIRMATION_TEXT:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "확인 문구가 일치하지 않습니다.")

    coordinator = request.app.state.season_reset_coordinator
    try:
        async with coordinator.reset():
            result = await _complete_reset_transaction(
                request.app.state.session_factory,
                admin.id,
            )
    except (SeasonResetAlreadyRunning, SeasonResetLockUnavailable) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "시즌 초기화가 이미 진행 중입니다.") from exc
    except SeasonResetConfigurationInvalid as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    try:
        await asyncio.wait_for(
            manager.broadcast_all({"type": "season.reset"}),
            timeout=RESET_BROADCAST_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.exception("Season reset broadcast failed")
    return result
