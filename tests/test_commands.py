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
    assert commands._summary_recording_filename("/요약 1번") == "1번"
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
    assert commands._resolve_recording_summary_filename("1번") == "voice-20260520-120000.jsonl"
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


def test_command_adapter_runs_command_then_replies_with_result(monkeypatch):
    sent_messages = []
    reply_kwargs = {}

    class FakeTyping:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class FakeChannel:
        def typing(self):
            return FakeTyping()

        async def send(self, content=None, **kwargs):
            sent_messages.append(content or "<embed>")

    async def fake_generate_reply(**kwargs):
        reply_kwargs.update(kwargs)
        return "결과에 4를 더하면 5야."

    monkeypatch.setattr(commands, "generate_reply", fake_generate_reply)

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
            user_text="/실행 주사위 1 1 | 주사위를 굴려서 나온 숫자에 4 더해줘",
            user_data={"name": "Alice", "nickname": "Alice", "affection": 50},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert sent_messages == [
        "주사위 결과: **1** (`1`~`1`)",
        "결과에 4를 더하면 5야.",
    ]
    assert reply_kwargs["user_message"] == "주사위를 굴려서 나온 숫자에 4 더해줘"
    assert "주사위 결과: **1**" in reply_kwargs["extra_context"]


def test_command_adapter_runs_multiple_commands_before_reply(monkeypatch):
    sent_messages = []
    reply_kwargs = {}

    class FakeTyping:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class FakeChannel:
        def typing(self):
            return FakeTyping()

        async def send(self, content=None, **kwargs):
            sent_messages.append(content or "<embed>")

    async def fake_generate_reply(**kwargs):
        reply_kwargs.update(kwargs)
        return "두 결과를 합치면 3이야."

    monkeypatch.setattr(commands, "generate_reply", fake_generate_reply)

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
            user_text="/실행 주사위 1 1 && 주사위 2 2 | 두 결과를 더해줘",
            user_data={"name": "Alice", "nickname": "Alice", "affection": 50},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert sent_messages == [
        "주사위 결과: **1** (`1`~`1`)",
        "주사위 결과: **2** (`2`~`2`)",
        "두 결과를 합치면 3이야.",
    ]
    assert "[1] 명령어: /주사위 1 1" in reply_kwargs["extra_context"]
    assert "[2] 명령어: /주사위 2 2" in reply_kwargs["extra_context"]


def test_web_command_adapter_uses_web_search_for_final_reply_only(monkeypatch):
    sent_messages = []
    reply_kwargs = {}

    class FakeTyping:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class FakeChannel:
        def typing(self):
            return FakeTyping()

        async def send(self, content=None, **kwargs):
            sent_messages.append(content or "<embed>")

    async def fake_generate_reply(**kwargs):
        reply_kwargs.update(kwargs)
        return "검색해서 답했어."

    monkeypatch.setattr(commands, "generate_reply", fake_generate_reply)

    message = SimpleNamespace(
        author=SimpleNamespace(
            id=commands.SPECIAL_USER_ID,
            name="Owner",
            display_name="Owner",
        ),
        channel=FakeChannel(),
        mentions=[],
        guild=None,
    )
    client = SimpleNamespace(user=SimpleNamespace(id=999))

    asyncio.run(
        commands.handle_mentioned_message(
            message=message,
            user_text="/검색실행 최신 AI 소식 알려줘",
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={"internet_mode": False},
            client=client,
        )
    )

    assert sent_messages == ["검색해서 답했어."]
    assert reply_kwargs["user_message"] == "최신 AI 소식 알려줘"
    assert reply_kwargs["force_web_search"] is True
    assert reply_kwargs["extra_context"] is None


def test_auto_web_command_runs_search_adapter_without_echoing_command(monkeypatch):
    sent_messages = []
    reply_calls = []

    class FakeTyping:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class FakeChannel:
        def typing(self):
            return FakeTyping()

        async def send(self, content=None, **kwargs):
            sent_messages.append(content or "<embed>")

    async def fake_generate_reply(**kwargs):
        reply_calls.append(kwargs)
        if kwargs.get("allow_command_output", True):
            return "/검색실행 정왕역 근처 맛집 찾아줄 수 있어?"
        return "정왕역 근처 맛집을 찾아봤어."

    monkeypatch.setattr(commands, "generate_reply", fake_generate_reply)

    message = SimpleNamespace(
        author=SimpleNamespace(
            id=commands.SPECIAL_USER_ID,
            name="Owner",
            display_name="Owner",
        ),
        channel=FakeChannel(),
        mentions=[],
        guild=None,
    )
    client = SimpleNamespace(user=SimpleNamespace(id=999))

    asyncio.run(
        commands.handle_mentioned_message(
            message=message,
            user_text="정왕역 근처 맛집 찾아줄 수 있어?",
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={"internet_mode": False},
            client=client,
        )
    )

    assert sent_messages == ["정왕역 근처 맛집을 찾아봤어."]
    assert len(reply_calls) == 2
    assert reply_calls[1]["force_web_search"] is True
    assert reply_calls[1]["allow_command_output"] is False


def test_command_adapter_blocks_persistent_internet_mode():
    sent_messages = []

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent_messages.append(content or "<embed>")

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
            user_text="/실행 인터넷모드 on | 이번 답변에서 검색해줘",
            user_data={"name": "Alice", "nickname": "Alice", "affection": 50},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert sent_messages == [
        "…`/실행` 안에서는 `/인터넷모드` 대신 `/검색실행`을 써줘. 그 답변 한 번에만 인터넷 검색을 사용할게."
    ]


def test_web_command_adapter_rejects_non_special_user():
    sent_messages = []

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent_messages.append(content or "<embed>")

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
            user_text="/검색실행 최신 AI 소식 알려줘",
            user_data={"name": "Alice", "nickname": "Alice", "affection": 50},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert sent_messages == ["…인터넷 검색 실행은 특별 사용자만 사용할 수 있어."]

