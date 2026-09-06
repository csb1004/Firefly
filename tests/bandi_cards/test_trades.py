import asyncio
import threading
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.websockets import WebSocketDisconnect

from bandi_cards.models import Card, Inventory, TradeRoom, User, WebSocketTicket, utcnow
from bandi_cards.realtime.connection_manager import ConnectionManager
from bandi_cards.security import random_token, token_hash
from bandi_cards.season_reset import SeasonResetCoordinator
from bandi_cards.services.trades import (
    accept_invite,
    accept_offer,
    cancel_trade,
    create_trade,
    mark_user_reconnecting,
    restore_user_rooms,
    set_offer,
)


@contextmanager
def held_reset(coordinator):
    entered = threading.Event()
    release = threading.Event()

    def hold() -> None:
        async def scenario() -> None:
            async with coordinator.reset():
                entered.set()
                await asyncio.to_thread(release.wait)

        asyncio.run(scenario())

    thread = threading.Thread(target=hold)
    thread.start()
    assert entered.wait(timeout=2)
    try:
        yield
    finally:
        release.set()
        thread.join(timeout=2)


def trade_setup(db):
    first = User(discord_id="trade-a", username="a", warning_acknowledged=True)
    second = User(discord_id="trade-b", username="b", warning_acknowledged=True)
    third = User(discord_id="trade-c", username="c", warning_acknowledged=True)
    purple = Card(name="보라 카드", rarity=4, yp=400, image_key="cards/purple.webp")
    gold = Card(name="금 카드", rarity=5, yp=900, image_key="cards/gold.webp")
    db.add_all([first, second, third, purple, gold])
    db.flush()
    db.add_all(
        [
            Inventory(user_id=first.id, card_id=purple.id, quantity=3),
            Inventory(user_id=second.id, card_id=gold.id, quantity=2),
        ]
    )
    db.commit()
    return first, second, third, purple, gold


def negotiating_room(db, first, second):
    room = create_trade(db, first.id, second.id)
    return accept_invite(db, room.id, second.id)


def socket_ticket(web_db, *, discord_id: str) -> tuple[str, int]:
    raw = random_token()
    with web_db() as db:
        user = User(discord_id=discord_id, username=discord_id, warning_acknowledged=True)
        db.add(user)
        db.flush()
        db.add(
            WebSocketTicket(
                token_hash=token_hash(raw),
                user_id=user.id,
                expires_at=utcnow() + timedelta(seconds=60),
            )
        )
        db.commit()
        return raw, user.id


class ControlledWebSocket:
    def __init__(self, coordinator: SeasonResetCoordinator) -> None:
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                season_reset_coordinator=coordinator,
            )
        )
        self.headers: dict[str, str] = {}
        self.accept_started = asyncio.Event()
        self.accept_release = asyncio.Event()
        self.receive_release = asyncio.Event()
        self.closed: list[int] = []
        self.sent: list[dict] = []

    async def accept(self) -> None:
        self.accept_started.set()
        await self.accept_release.wait()

    async def close(self, code: int) -> None:
        self.closed.append(code)

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)

    async def receive_json(self) -> dict:
        await self.receive_release.wait()
        raise WebSocketDisconnect(code=1000)


def test_offer_reservation_blocks_other_rooms_and_cancel_releases(web_db):
    with web_db() as db:
        first, second, third, purple, _gold = trade_setup(db)
        room = negotiating_room(db, first, second)
        set_offer(db, room.id, first.id, purple.id, 2)
        assert db.get(Inventory, (first.id, purple.id)).reserved_quantity == 2

        other = negotiating_room(db, first, third)
        with pytest.raises(HTTPException) as error:
            set_offer(db, other.id, first.id, purple.id, 2)
        assert error.value.status_code == 409

        cancel_trade(db, room.id, first.id)
        assert db.get(Inventory, (first.id, purple.id)).reserved_quantity == 0
        set_offer(db, other.id, first.id, purple.id, 2)


def test_offer_change_clears_acceptance_and_completion_preserves_totals(web_db):
    with web_db() as db:
        first, second, _third, purple, gold = trade_setup(db)
        room = negotiating_room(db, first, second)
        set_offer(db, room.id, first.id, purple.id, 2)
        set_offer(db, room.id, second.id, gold.id, 1)
        room, completed = accept_offer(db, room.id, first.id)
        assert completed is False
        assert room.inviter_accepted_version == room.offer_version

        set_offer(db, room.id, second.id, gold.id, 2)
        assert room.inviter_accepted_version is None
        accept_offer(db, room.id, first.id)
        room, completed = accept_offer(db, room.id, second.id)
        assert completed is True
        assert room.status == "completed"
        assert db.get(Inventory, (first.id, purple.id)).quantity == 1
        assert db.get(Inventory, (second.id, purple.id)).quantity == 2
        assert db.get(Inventory, (second.id, gold.id)).quantity == 0
        assert db.get(Inventory, (first.id, gold.id)).quantity == 2
        total_purple = sum(item.quantity for item in db.query(Inventory).filter_by(card_id=purple.id))
        total_gold = sum(item.quantity for item in db.query(Inventory).filter_by(card_id=gold.id))
        assert (total_purple, total_gold) == (3, 2)
        assert all(item.reserved_quantity == 0 for item in db.query(Inventory).all())


def test_reconnect_only_restores_when_both_participants_are_online(web_db):
    with web_db() as db:
        first, second, _third, _purple, _gold = trade_setup(db)
        room = negotiating_room(db, first, second)
        mark_user_reconnecting(db, first.id)
        assert db.get(TradeRoom, room.id).status == "reconnecting"

        online = {first.id}
        assert restore_user_rooms(db, first.id, lambda user_id: user_id in online) == []
        online.add(second.id)
        assert restore_user_rooms(db, second.id, lambda user_id: user_id in online) == [room.id]
        assert db.get(TradeRoom, room.id).status == "negotiating"


def test_websocket_ticket_is_single_use(web_client, web_db):
    raw = random_token()
    with web_db() as db:
        user = User(discord_id="socket-user", username="socket", warning_acknowledged=True)
        db.add(user)
        db.flush()
        db.add(
            WebSocketTicket(
                token_hash=token_hash(raw),
                user_id=user.id,
                expires_at=utcnow() + timedelta(seconds=60),
            )
        )
        db.commit()
        user_id = user.id

    with web_client.websocket_connect(f"/ws?ticket={raw}") as websocket:
        assert websocket.receive_json() == {"type": "presence.ready", "user_id": user_id}
        websocket.send_json({"type": "ping"})
        assert websocket.receive_json() == {"type": "pong"}

    with web_db() as db:
        assert db.get(WebSocketTicket, token_hash(raw)).consumed_at is not None


def test_websocket_ticket_consume_and_registration_are_one_reset_guard(web_db, monkeypatch):
    from bandi_cards.routes import trades

    raw, user_id = socket_ticket(web_db, discord_id="guarded-handshake-user")

    async def scenario() -> None:
        coordinator = SeasonResetCoordinator()
        local_manager = ConnectionManager()
        websocket = ControlledWebSocket(coordinator)
        websocket.app.state.session_factory = web_db
        monkeypatch.setattr(trades, "manager", local_manager)

        socket_task = asyncio.create_task(trades.realtime_socket(websocket, raw))
        await asyncio.wait_for(websocket.accept_started.wait(), timeout=0.2)
        reset_entered = asyncio.Event()
        online_during_reset: list[bool] = []

        async def reset() -> None:
            async with coordinator.reset():
                online_during_reset.append(local_manager.is_online(user_id))
                reset_entered.set()
                await local_manager.broadcast_all({"type": "season.reset"})

        reset_task = asyncio.create_task(reset())
        try:
            await asyncio.sleep(0)
            assert reset_entered.is_set() is False

            websocket.accept_release.set()
            await asyncio.wait_for(reset_entered.wait(), timeout=0.2)
            await reset_task
            assert online_during_reset == [True]
            assert {"type": "season.reset"} in websocket.sent
        finally:
            websocket.accept_release.set()
            websocket.receive_release.set()
            await asyncio.gather(socket_task, reset_task, return_exceptions=True)

    asyncio.run(scenario())


def test_stalled_websocket_accept_times_out_and_closes_without_registration(web_db, monkeypatch):
    from bandi_cards.routes import trades

    raw, user_id = socket_ticket(web_db, discord_id="stalled-handshake-user")

    async def scenario() -> None:
        coordinator = SeasonResetCoordinator()
        local_manager = ConnectionManager()
        local_manager.accept_timeout_seconds = 0.01
        websocket = ControlledWebSocket(coordinator)
        websocket.app.state.session_factory = web_db
        monkeypatch.setattr(trades, "manager", local_manager)

        await asyncio.wait_for(trades.realtime_socket(websocket, raw), timeout=0.2)

        assert websocket.accept_started.is_set() is True
        assert websocket.closed == [1013]
        assert local_manager.is_online(user_id) is False
        assert user_id not in local_manager.connections
        async with coordinator.reset():
            assert coordinator.is_resetting is True

    asyncio.run(scenario())


def test_websocket_handshake_closes_with_1013_during_reset(web_client):
    with held_reset(web_client.app.state.season_reset_coordinator):
        with pytest.raises(WebSocketDisconnect) as caught:
            with web_client.websocket_connect("/ws?ticket=unused"):
                pass
    assert caught.value.code == 1013


def test_open_websocket_does_not_hold_the_reset_coordinator(web_client, web_db):
    raw = random_token()
    with web_db() as db:
        user = User(discord_id="open-socket-user", username="open_socket", warning_acknowledged=True)
        db.add(user)
        db.flush()
        db.add(
            WebSocketTicket(
                token_hash=token_hash(raw),
                user_id=user.id,
                expires_at=utcnow() + timedelta(seconds=60),
            )
        )
        db.commit()

    with web_client.websocket_connect(f"/ws?ticket={raw}") as websocket:
        websocket.receive_json()
        with held_reset(web_client.app.state.season_reset_coordinator):
            websocket.send_json({"type": "ping"})
            assert websocket.receive_json() == {"type": "pong"}
