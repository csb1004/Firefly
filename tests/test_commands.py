import asyncio
from types import SimpleNamespace

from firefly import commands


def test_matches_command_requires_exact_command_or_space_boundary():
    assert commands.matches_command("/요약", "/요약")
    assert commands.matches_command("/요약 10", "/요약")
    assert not commands.matches_command("/요약하기", "/요약")


def test_special_only_command_detection_uses_registered_prefixes():
    command = commands.SPECIAL_ONLY_COMMAND_PREFIXES[0]

    assert commands.is_special_only_command(command)
    assert commands.is_special_only_command(f"{command} extra")
    assert not commands.is_special_only_command("/not-special")


def test_parse_summary_args_defaults_to_room_when_group_mode_is_on():
    scope, limit = commands._parse_summary_args("/요약", {"group_mode": True})

    assert scope == "room"
    assert limit == commands.SUMMARY_DEFAULT_LIMIT


def test_parse_summary_args_supports_english_scope_and_clamps_limit():
    assert commands._parse_summary_args("/요약 user 0", {"group_mode": True}) == ("user", 1)
    assert commands._parse_summary_args("/요약 room 999", {"group_mode": False}) == ("room", 80)


def test_summary_recording_filename_ignores_summary_scope_and_limits():
    assert commands._summary_recording_filename("/요약") is None
    assert commands._summary_recording_filename("/요약 room 10") is None
    assert commands._summary_recording_filename("/요약 10") is None
    assert commands._summary_recording_filename("/요약 voice-20260516.jsonl") == "voice-20260516.jsonl"


def test_extract_auto_command_requires_first_response_line_to_be_command():
    assert commands._extract_auto_command("/요약") == "/요약"
    assert commands._extract_auto_command("  /투표 저녁 | 항목수=2 | 치킨 | 피자  ") == (
        "/투표 저녁 | 항목수=2 | 치킨 | 피자"
    )
    assert commands._extract_auto_command("/투표 저녁 | 항목수=2 | 치킨 | 피자\n잠깐만.") is None
    assert commands._extract_auto_command("좋아. /요약") is None
    assert commands._extract_auto_command("/") is None


def test_resolve_recording_summary_filename_supports_latest_aliases(monkeypatch):
    monkeypatch.setattr(
        commands,
        "list_recordings",
        lambda: [{"filename": "voice-20260520-120000.jsonl"}],
    )

    assert commands._resolve_recording_summary_filename("최근") == "voice-20260520-120000.jsonl"
    assert commands._resolve_recording_summary_filename("latest") == "voice-20260520-120000.jsonl"
    assert commands._resolve_recording_summary_filename("voice-old.jsonl") == "voice-old.jsonl"


def test_resolve_recording_summary_filename_returns_none_without_recordings(monkeypatch):
    monkeypatch.setattr(commands, "list_recordings", lambda: [])

    assert commands._resolve_recording_summary_filename("최근") is None


def test_auto_command_runs_with_original_message_author(monkeypatch):
    sent_messages = []
    updated_users = []

    class FakeTyping:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class FakeChannel:
        def typing(self):
            return FakeTyping()

        async def send(self, content=None, **kwargs):
            sent_messages.append(content)

    async def fake_generate_reply(**kwargs):
        return "/호칭 새별"

    def fake_update_user_data(user_id, user_data):
        updated_users.append((user_id, dict(user_data)))

    monkeypatch.setattr(commands, "generate_reply", fake_generate_reply)
    monkeypatch.setattr(commands, "update_user_data", fake_update_user_data)

    message = SimpleNamespace(
        author=SimpleNamespace(id=123, name="Alice", display_name="Alice"),
        channel=FakeChannel(),
        mentions=[],
        guild=None,
    )
    client = SimpleNamespace(user=SimpleNamespace(id=999))
    user_data = {"name": "Alice", "nickname": "Alice", "affection": 50}

    asyncio.run(
        commands.handle_mentioned_message(
            message=message,
            user_text="나를 새별이라고 불러줘",
            user_data=user_data,
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert updated_users == [(123, {"name": "Alice", "nickname": "새별", "affection": 50})]
    assert sent_messages == ["응. 이제부터는 새별(이)라고 불러볼게."]

