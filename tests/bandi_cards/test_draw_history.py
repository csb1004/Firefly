from datetime import datetime, timezone

from bandi_cards.models import Card, DrawHistory, DrawState
from bandi_cards.services.draws import logical_draw_day


def test_personal_draw_history_is_numbered_newest_first_and_paginated(signed_in):
    client, factory, user_id, csrf = signed_in
    client.post("/api/me/warning", headers={"X-CSRF-Token": csrf})
    with factory() as db:
        cards = [
            Card(name="첫 카드", rarity=1, yp=10, image_key="cards/first.webp"),
            Card(name="둘째 카드", rarity=4, yp=400, image_key="cards/second.webp"),
            Card(name="셋째 카드", rarity=5, yp=500, image_key="cards/third.webp"),
        ]
        db.add_all(cards)
        db.flush()
        for index, card in enumerate(cards, start=1):
            drawn_at = datetime(2026, 8, 20, index, tzinfo=timezone.utc)
            db.add(DrawHistory(
                user_id=user_id,
                card_id=card.id,
                card_name=card.name,
                card_rarity=card.rarity,
                card_yp=card.yp,
                draw_day=logical_draw_day(drawn_at),
                ticket_source="daily" if index < 3 else "bonus",
                idempotency_key=f"history-{index}",
                drawn_at=drawn_at,
            ))
        db.add(DrawState(user_id=user_id, pulls_since_four_plus=2, pulls_since_five=15))
        db.commit()

    first_page = client.get("/api/draw/history", params={"page": 1, "page_size": 2})
    assert first_page.status_code == 200
    payload = first_page.json()
    assert payload["total"] == 3
    assert payload["summary"] == {"total_draws": 3, "four_remaining": 8, "five_remaining": 75}
    assert [(item["draw_number"], item["card_name"]) for item in payload["items"]] == [
        (3, "셋째 카드"),
        (2, "둘째 카드"),
    ]
    assert payload["items"][0]["ticket_source"] == "bonus"
    assert payload["items"][0]["image_url"].endswith("/cards/third.webp")

    second_page = client.get("/api/draw/history", params={"page": 2, "page_size": 2}).json()
    assert [(item["draw_number"], item["card_name"]) for item in second_page["items"]] == [(1, "첫 카드")]
