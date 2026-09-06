import asyncio
import threading
from contextlib import contextmanager
from datetime import timedelta

import pytest
from fastapi import HTTPException
from starlette.websockets import WebSocketDisconnect

from bandi_cards.models import Card, Inventory, TradeRoom, User, WebSocketTicket, utcnow
from bandi_cards.security import random_token, token_hash
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
