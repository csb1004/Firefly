from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import SessionLocal, get_db
from ..models import TradeRoom, User, WebSocketTicket, as_utc, utcnow
from ..realtime.connection_manager import WebSocketAcceptTimeout, manager
from ..season_reset import SeasonResetInProgress, track_season_mutation
from ..security import require_csrf_user, require_ready_user, token_hash
from ..services.trades import (
    accept_invite,
    accept_offer,
    add_request,
    cancel_trade,
    cancel_user_rooms,
    create_trade,
    mark_user_reconnecting,
    participants,
    require_participant,
    restore_user_rooms,
    room_payload,
    set_offer,
)


router = APIRouter(tags=["live trades"])
WEBSOCKET_CLOSE_TIMEOUT_SECONDS = 1.0


class InviteBody(BaseModel):
    invitee_id: int


class OfferBody(BaseModel):
    card_id: str
    quantity: int = Field(ge=0)


class RequestBody(BaseModel):
    card_id: str | None = None
    quantity: int | None = Field(default=None, ge=1)
    message: str | None = Field(default=None, max_length=200)


class InvalidWebSocketTicket(RuntimeError):
    """Raised when a websocket ticket cannot be consumed."""


async def close_socket(websocket: WebSocket, code: int) -> None:
    try:
        await asyncio.wait_for(
            websocket.close(code=code),
            timeout=WEBSOCKET_CLOSE_TIMEOUT_SECONDS,
        )
    except Exception:
        pass


async def broadcast_room(db: Session, room: TradeRoom, event: str = "trade.updated") -> None:
    await manager.send_many(participants(room), {"type": event, "room": room_payload(db, room)})


@router.get("/api/presence/{user_id}")
def presence(user_id: int, _: User = Depends(require_ready_user)) -> dict:
    return {"user_id": user_id, "online": manager.is_online(user_id)}


@router.post("/api/trades/invite", status_code=201)
async def invite_trade(
    body: InviteBody,
    inviter: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
    _season_mutation: None = Depends(track_season_mutation),
) -> dict:
    if not manager.is_online(body.invitee_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "온라인 사용자만 거래에 초대할 수 있습니다.")
    room = create_trade(db, inviter.id, body.invitee_id)
    await broadcast_room(db, room, "trade.invited")
    return room_payload(db, room)


@router.get("/api/trades/{room_id}")
def get_trade(room_id: str, user: User = Depends(require_ready_user), db: Session = Depends(get_db)) -> dict:
    room = require_participant(db.get(TradeRoom, room_id), user.id)
    return room_payload(db, room)


@router.post("/api/trades/{room_id}/accept-invite")
async def trade_accept_invite(
    room_id: str,
    user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
    _season_mutation: None = Depends(track_season_mutation),
) -> dict:
    room = accept_invite(db, room_id, user.id)
    await broadcast_room(db, room)
    return room_payload(db, room)


@router.put("/api/trades/{room_id}/offer")
async def trade_offer(
    room_id: str,
    body: OfferBody,
    user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
    _season_mutation: None = Depends(track_season_mutation),
) -> dict:
    room = set_offer(db, room_id, user.id, body.card_id, body.quantity)
    await broadcast_room(db, room)
    return room_payload(db, room)


@router.post("/api/trades/{room_id}/request")
async def trade_request(
    room_id: str,
    body: RequestBody,
    user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
    _season_mutation: None = Depends(track_season_mutation),
) -> dict:
    add_request(db, room_id, user.id, card_id=body.card_id, quantity=body.quantity, message=body.message)
    room = db.get(TradeRoom, room_id)
    await broadcast_room(db, room)
    return room_payload(db, room)


@router.post("/api/trades/{room_id}/accept")
async def trade_accept(
    room_id: str,
    user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
    _season_mutation: None = Depends(track_season_mutation),
) -> dict:
    room, completed = accept_offer(db, room_id, user.id)
    await broadcast_room(db, room, "trade.completed" if completed else "trade.updated")
    return room_payload(db, room)


@router.post("/api/trades/{room_id}/cancel")
async def trade_cancel(
    room_id: str,
    user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
    _season_mutation: None = Depends(track_season_mutation),
) -> dict:
    room = cancel_trade(db, room_id, user.id)
    await broadcast_room(db, room, "trade.cancelled")
    return room_payload(db, room)


async def expire_disconnect(user_id: int, factory, coordinator) -> None:
    try:
        await asyncio.sleep(15)
        notifications = []
        try:
            async with coordinator.mutation():
                with factory() as db:
                    room_ids = cancel_user_rooms(db, user_id)
                    for room_id in room_ids:
                        room = db.get(TradeRoom, room_id)
                        notifications.append(
                            (
                                participants(room),
                                {"type": "trade.cancelled", "room": room_payload(db, room)},
                            )
                        )
        except SeasonResetInProgress:
            return
        for user_ids, message in notifications:
            await manager.send_many(user_ids, message)
    except asyncio.CancelledError:
        return
    finally:
        manager.disconnect_tasks.pop(user_id, None)


@router.websocket("/ws")
async def realtime_socket(websocket: WebSocket, ticket: str):
    origin = websocket.headers.get("origin")
    from ..config import settings

    if origin and origin.rstrip("/") != settings.public_url:
        await close_socket(websocket, 1008)
        return
    factory = getattr(websocket.app.state, "session_factory", SessionLocal)
    coordinator = websocket.app.state.season_reset_coordinator
    try:
        async with coordinator.mutation():
            with factory() as db:
                record = db.get(WebSocketTicket, token_hash(ticket))
                if record is None or record.consumed_at is not None or as_utc(record.expires_at) <= utcnow():
                    raise InvalidWebSocketTicket
                record.consumed_at = utcnow()
                user_id = record.user_id
                db.commit()
            was_offline = await manager.connect(user_id, websocket)
    except SeasonResetInProgress:
        await close_socket(websocket, 1013)
        return
    except InvalidWebSocketTicket:
        await close_socket(websocket, 1008)
        return
    except WebSocketAcceptTimeout:
        await close_socket(websocket, 1013)
        return
    if was_offline:
        try:
            async with coordinator.mutation():
                with factory() as db:
                    restore_user_rooms(db, user_id, manager.is_online)
        except SeasonResetInProgress:
            pass
    await manager.send(user_id, {"type": "presence.ready", "user_id": user_id})
    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        if manager.disconnect(user_id, websocket):
            try:
                async with coordinator.mutation():
                    with factory() as db:
                        mark_user_reconnecting(db, user_id)
            except SeasonResetInProgress:
                pass
            else:
                manager.disconnect_tasks[user_id] = asyncio.create_task(
                    expire_disconnect(user_id, factory, coordinator)
                )
