import asyncio
import importlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from bandi_cards.models import Card, Inventory, User
from bandi_cards.services.season_reset import execute_season_reset
from firefly import commands


def _card_commands_module():
    spec = importlib.util.find_spec("firefly.card_commands")
    assert spec is not None, "card site Discord commands are not implemented"
    return importlib.import_module("firefly.card_commands")


def test_gacha_embed_links_to_configured_card_site(monkeypatch):
    card_commands = _card_commands_module()
    monkeypatch.setattr(card_commands, "CARD_SITE_URL", "https://cards.example")

    embed = card_commands.create_gacha_embed()

    assert embed.title == "영호 가챠"
    assert embed.url == "https://cards.example"
    assert "https://cards.example" in embed.description


def test_ranking_embed_shows_global_top_ten_and_requester_rank(web_db, monkeypatch):
    card_commands = _card_commands_module()
    monkeypatch.setattr(card_commands, "CARD_SITE_URL", "https://cards.example")
    with web_db() as db:
        card = Card(name="랭킹 카드", rarity=5, yp=100, image_key="cards/rank.webp")
        users = [
            User(discord_id=str(1000 + index), username=f"user{index}", global_name=f"유저 {index}")
            for index in range(12)
        ]
        db.add_all([card, *users])
        db.flush()
        for index, user in enumerate(users):
            db.add(Inventory(user_id=user.id, card_id=card.id, quantity=12 - index))
        db.commit()

    embed = card_commands.create_ranking_embed("1011", session_factory=web_db)
    fields = {field.name: field.value for field in embed.fields}

    assert embed.title == "영호 가챠 YP 랭킹"
    assert embed.url == "https://cards.example/ranking"
    assert len(embed.description.splitlines()) == 10
    assert "1. 유저 0 (@user0) — 1,200 YP" in embed.description
    assert fields["내 순위"] == "12위 · 100 YP"
    assert fields["전체 랭킹"] == "https://cards.example/ranking"


def test_ranking_embed_guides_unregistered_user_to_login(web_db, monkeypatch):
    card_commands = _card_commands_module()
    monkeypatch.setattr(card_commands, "CARD_SITE_URL", "https://cards.example")

    embed = card_commands.create_ranking_embed("9999", session_factory=web_db)
    fields = {field.name: field.value for field in embed.fields}

    assert fields["내 순위"] == "아직 가입하지 않았어. 영호 가챠에 로그인해줘!"
    assert "https://cards.example" in embed.description


def test_ranking_embed_keeps_existing_users_at_zero_after_season_reset(web_db, monkeypatch):
    card_commands = _card_commands_module()
    monkeypatch.setattr(card_commands, "CARD_SITE_URL", "https://cards.example")

    with web_db() as db:
        users = [
            User(discord_id="2001", username="alpha", global_name="알파"),
            User(discord_id="2002", username="beta", global_name="베타"),
        ]
        cards = [
            Card(
                name=f"시즌 보존 카드 {rarity}",
                rarity=rarity,
                yp=rarity * 100,
                image_key=f"cards/season-{rarity}.webp",
            )
            for rarity in range(1, 6)
        ]
        db.add_all([*users, *cards])
        db.flush()
        db.add_all(
            [
                Inventory(user_id=users[0].id, card_id=cards[4].id, quantity=3),
                Inventory(user_id=users[1].id, card_id=cards[2].id, quantity=2),
            ]
        )
        db.commit()
        admin_id = users[0].id

    with web_db() as db:
        execute_season_reset(db, admin_id=admin_id)
        db.commit()

    embed = card_commands.create_ranking_embed("2002", session_factory=web_db)
    fields = {field.name: field.value for field in embed.fields}

    assert embed.url == "https://cards.example/ranking"
    assert embed.description.splitlines() == [
        "1. 알파 (@alpha) — 0 YP",
        "2. 베타 (@beta) — 0 YP",
    ]
    assert fields["내 순위"] == "2위 · 0 YP"
    assert fields["전체 랭킹"] == "https://cards.example/ranking"


def _run_text_command(command_text, monkeypatch):
    sent = []

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent.append((content, kwargs))

    marker = SimpleNamespace(title=command_text)
    monkeypatch.setattr(commands, "create_gacha_embed", lambda: marker, raising=False)
    monkeypatch.setattr(
        commands,
        "create_ranking_embed",
        lambda discord_id: marker,
        raising=False,
    )
    message = SimpleNamespace(
        author=SimpleNamespace(id=123, name="Alice", display_name="Alice"),
        channel=FakeChannel(),
        mentions=[],
        guild=None,
    )
    client = SimpleNamespace(user=SimpleNamespace(id=999))
    asyncio.run(
        commands.handle_mentioned_message(
            message=message,
            user_text=command_text,
            user_data={"name": "Alice", "nickname": "Alice", "affection": 50},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )
    return sent, marker


def test_gacha_text_command_sends_site_embed(monkeypatch):
    sent, marker = _run_text_command("/가챠", monkeypatch)

    assert sent == [(None, {"embed": marker})]


def test_ranking_text_command_sends_personal_ranking_embed(monkeypatch):
    sent, marker = _run_text_command("/랭킹", monkeypatch)

    assert sent == [(None, {"embed": marker})]


def test_card_site_slash_commands_are_registered():
    firefly = importlib.import_module("Firefly")

    assert firefly.tree.get_command("가챠") is not None
    assert firefly.tree.get_command("랭킹") is not None


def test_command_behavior_guide_knows_card_site_commands():
    guide = Path("prompt_commands_general.txt").read_text(encoding="utf-8")

    assert "- `/가챠`" in guide
    assert "- `/랭킹`" in guide
    assert '"가챠 사이트 주소 알려줘" -> `/가챠`' in guide
    assert '"내 랭킹 보여줘" -> `/랭킹`' in guide
