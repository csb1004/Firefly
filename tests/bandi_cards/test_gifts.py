import pytest
from fastapi import HTTPException

from bandi_cards.models import Card, Inventory, NotificationOutbox, User
from bandi_cards.services.draws import collection_yp
from bandi_cards.services.gifts import preview_gift, send_gift


def gift_setup(db):
    sender = User(discord_id="gift-sender", username="sender", warning_acknowledged=True)
    receiver = User(discord_id="gift-receiver", username="receiver", warning_acknowledged=True)
    card = Card(name="선물 카드", rarity=4, yp=400, image_key="cards/gift.webp")
    db.add_all([sender, receiver, card])
    db.flush()
    db.add(Inventory(user_id=sender.id, card_id=card.id, quantity=5))
    db.commit()
    return sender, receiver, card


def test_gift_preview_shows_yp_effect_for_every_transferred_copy(web_db):
    with web_db() as db:
        sender, receiver, card = gift_setup(db)
        partial = preview_gift(db, sender.id, receiver.id, card.id, 4)
        assert partial.sender_yp_change == -1600
        assert partial.receiver_yp_change == 1600
        last = preview_gift(db, sender.id, receiver.id, card.id, 5)
        assert last.sender_yp_change == -2000
        assert last.receiver_yp_change == 2000


def test_gift_transfers_once_and_creates_outbox_in_same_commit(web_db):
    with web_db() as db:
        sender, receiver, card = gift_setup(db)
        gift, preview, repeated = send_gift(db, sender.id, receiver.id, card.id, 4, "gift-idempotency")
        assert repeated is False
        assert db.get(Inventory, (sender.id, card.id)).quantity == 1
        assert db.get(Inventory, (receiver.id, card.id)).quantity == 4
        assert collection_yp(db, sender.id) == 400
        assert collection_yp(db, receiver.id) == 1600
        assert db.query(NotificationOutbox).count() == 1

        same, same_preview, repeated = send_gift(db, sender.id, receiver.id, card.id, 4, "gift-idempotency")
        assert repeated is True
        assert same.id == gift.id
        assert db.get(Inventory, (sender.id, card.id)).quantity == 1
        assert db.get(Inventory, (receiver.id, card.id)).quantity == 4
        assert db.query(NotificationOutbox).count() == 1


def test_reserved_cards_and_disabled_recipient_are_rejected(web_db):
    with web_db() as db:
        sender, receiver, card = gift_setup(db)
        inventory = db.get(Inventory, (sender.id, card.id))
        inventory.reserved_quantity = 4
        db.commit()
        with pytest.raises(HTTPException) as reserved:
            send_gift(db, sender.id, receiver.id, card.id, 2, "reserved-gift")
        assert reserved.value.status_code == 409

        inventory.reserved_quantity = 0
        receiver.accepts_gifts = False
        db.commit()
        with pytest.raises(HTTPException) as disabled:
            send_gift(db, sender.id, receiver.id, card.id, 1, "disabled-gift")
        assert disabled.value.status_code == 409
