import asyncio
from types import SimpleNamespace

from firefly import commands, nickname_commands, storage
from firefly.config import DAILY_NEWS_KEY, POLLS_KEY


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


def test_auto_command_runs_with_original_message_author(monkeypatch, tmp_path):
    sent_messages = []
    updated_users = []
    monkeypatch.setattr(storage, "MEMORY_FILE", tmp_path / "memory.json")

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
    monkeypatch.setattr(nickname_commands, "update_user_data", fake_update_user_data)

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


def test_natural_nickname_command_runs_without_model(monkeypatch):
    sent_messages = []
    updated_users = []

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent_messages.append(content)

    async def fail_generate_reply(**kwargs):
        raise AssertionError("natural command should not call the model")

    def fake_update_user_data(user_id, user_data):
        updated_users.append((user_id, dict(user_data)))

    monkeypatch.setattr(commands, "generate_reply", fail_generate_reply)
    monkeypatch.setattr(nickname_commands, "update_user_data", fake_update_user_data)

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
            user_text="칭호를 새별이라고 바꿔줘",
            user_data=user_data,
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert updated_users == [(123, {"name": "Alice", "nickname": "새별", "affection": 50})]
    assert sent_messages == ["응. 이제부터는 새별(이)라고 불러볼게."]


def test_special_user_changes_mentioned_user_nickname_from_natural_phrase(monkeypatch, tmp_path):
    sent_messages = []
    monkeypatch.setattr(storage, "MEMORY_FILE", tmp_path / "memory.json")
    storage.save_memory({
        "123": {"name": "IkaMom", "nickname": "개척자", "affection": 50},
    })

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent_messages.append(content or "<embed>")

    target = SimpleNamespace(id=123, name="IkaMom", display_name="이카맘", mention="<@123>")
    message = SimpleNamespace(
        author=SimpleNamespace(
            id=commands.SPECIAL_USER_ID,
            name="Owner",
            display_name="Owner",
        ),
        channel=FakeChannel(),
        mentions=[target],
        guild=None,
    )
    client = SimpleNamespace(user=SimpleNamespace(id=999))

    asyncio.run(
        commands.handle_mentioned_message(
            message=message,
            user_text="@이카맘의 칭호를 이카로 바꿔줘",
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert storage.load_memory()["123"]["nickname"] == "이카"
    assert sent_messages == ["…응. 이카맘의 호칭을 `이카`로 바꿨어."]


def test_special_user_changes_user_nickname_by_existing_nickname(monkeypatch, tmp_path):
    sent_messages = []
    monkeypatch.setattr(storage, "MEMORY_FILE", tmp_path / "memory.json")
    storage.save_memory({
        "123": {"name": "IkaMom", "nickname": "이카", "affection": 50},
    })

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent_messages.append(content or "<embed>")

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
            user_text="이카의 칭호를 이카2로 바꿔줘",
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert storage.load_memory()["123"]["nickname"] == "이카2"
    assert sent_messages == ["…응. IkaMom의 호칭을 `이카2`로 바꿨어."]


def test_special_user_nickname_lookup_rejects_ambiguous_existing_nickname(monkeypatch, tmp_path):
    sent_messages = []
    monkeypatch.setattr(storage, "MEMORY_FILE", tmp_path / "memory.json")
    storage.save_memory({
        "123": {"name": "IkaMom", "nickname": "이카", "affection": 50},
        "456": {"name": "IkaDad", "nickname": "이카", "affection": 50},
    })

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent_messages.append(content or "<embed>")

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
            user_text="이카의 칭호를 이카2로 바꿔줘",
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    data = storage.load_memory()
    assert data["123"]["nickname"] == "이카"
    assert data["456"]["nickname"] == "이카"
    assert "`이카` 호칭을 쓰는 사람이 2명" in sent_messages[0]


def test_nickname_change_rejects_duplicate_new_nickname(monkeypatch, tmp_path):
    sent_messages = []
    monkeypatch.setattr(storage, "MEMORY_FILE", tmp_path / "memory.json")
    storage.save_memory({
        "123": {"name": "IkaMom", "nickname": "이카", "affection": 50},
        "456": {"name": "IkaDad", "nickname": "이카2", "affection": 50},
    })

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent_messages.append(content or "<embed>")

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
            user_text="이카의 칭호를 이카2로 바꿔줘",
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert storage.load_memory()["123"]["nickname"] == "이카"
    assert "`이카2` 호칭은 이미" in sent_messages[0]


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
    assert reply_kwargs["persist_command_reply"] is False


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
    assert reply_kwargs["persist_command_reply"] is False


def test_command_adapter_runs_result_dependent_followup_command(monkeypatch):
    sent_messages = []
    reply_calls = []
    poll_commands = []

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
        if len(reply_calls) == 1:
            return "/투표 내일 점심밥 | 항목수=2 | 김밥 | 라멘 | 10분"
        return "주사위가 2라서 두 항목으로 투표를 올렸어."

    async def fake_create_poll_from_command(message, user_text, client):
        poll_commands.append(user_text)
        await message.channel.send("투표 생성됨: 내일 점심밥")

    monkeypatch.setattr(commands, "generate_reply", fake_generate_reply)
    monkeypatch.setattr(commands, "create_poll_from_command", fake_create_poll_from_command)

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
            user_text="/실행 주사위 2 2 | 2~6 주사위 굴려서 나온 숫자만큼 투표 항목 만들어줘. 투표 주제는 내일 점심밥",
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert sent_messages == [
        "주사위 결과: **2** (`2`~`2`)",
        "투표 생성됨: 내일 점심밥",
        "주사위가 2라서 두 항목으로 투표를 올렸어.",
    ]
    assert poll_commands == ["/투표 내일 점심밥 | 항목수=2 | 김밥 | 라멘 | 10분"]
    assert len(reply_calls) == 2
    assert reply_calls[0]["allow_command_output"] is True
    assert "주사위 결과: **2**" in reply_calls[0]["extra_context"]
    assert reply_calls[1]["allow_command_output"] is True
    assert "[2] 명령어: /투표 내일 점심밥" in reply_calls[1]["extra_context"]


def test_command_adapter_stops_result_dependent_loop_at_limit(monkeypatch):
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
        return "/주사위 1 1"

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
            user_text="/실행 주사위 1 1 | 계속 굴려줘",
            user_data={"name": "Alice", "nickname": "Alice", "affection": 50},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert sent_messages.count("주사위 결과: **1** (`1`~`1`)") == commands.MAX_ADAPTER_COMMANDS
    assert sent_messages[-1] == commands.ADAPTER_CHAIN_LIMIT_MESSAGE
    assert reply_calls[-1]["allow_command_output"] is False


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
    assert reply_kwargs["persist_command_reply"] is False


def test_auto_web_command_runs_search_adapter_without_echoing_command(monkeypatch, tmp_path):
    sent_messages = []
    reply_calls = []
    monkeypatch.setattr(storage, "MEMORY_FILE", tmp_path / "memory.json")

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
    assert reply_calls[0]["persist_command_reply"] is False
    assert reply_calls[1]["force_web_search"] is True
    assert reply_calls[1]["allow_command_output"] is False
    assert reply_calls[1]["persist_command_reply"] is False


def test_auto_command_failure_is_recorded_for_followup_context(monkeypatch, tmp_path):
    sent_messages = []
    monkeypatch.setattr(storage, "MEMORY_FILE", tmp_path / "memory.json")

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
        return "/투표 내일 점심밥 | 항목수=3 | 김밥 | 라멘 | 10분"

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
            user_text="내일 점심밥 후보 3개로 투표 만들어줘",
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    history = storage.load_memory()[str(commands.SPECIAL_USER_ID)]["history"]

    assert "항목수를 3개로 적었지만 실제 항목은 2개" in sent_messages[0]
    assert history[-2]["role"] == "user"
    assert history[-2]["content"] == "내일 점심밥 후보 3개로 투표 만들어줘"
    assert history[-1]["role"] == "assistant"
    assert "자동 명령 실행 기록" in history[-1]["content"]
    assert "/투표 내일 점심밥" in history[-1]["content"]
    assert "항목수를 3개로 적었지만 실제 항목은 2개" in history[-1]["content"]


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

    assert sent_messages == ["…인터넷 검색 실행 권한이 없어."]


def test_reasoning_command_updates_room_setting(monkeypatch, tmp_path):
    sent_messages = []
    monkeypatch.setattr(storage, "MEMORY_FILE", tmp_path / "memory.json")
    room_data = storage.get_room_data("room-1")

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent_messages.append(content or "<embed>")

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
            user_text="/추론 높음",
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data=room_data,
            client=client,
        )
    )

    assert storage.load_memory()[storage.ROOMS_KEY]["room-1"]["reasoning_effort"] == "high"
    assert sent_messages == ["…응. 이 방의 추론 단계를 `높음`으로 맞췄어."]


def test_brain_commands_add_update_and_delete_notes(monkeypatch, tmp_path):
    sent_messages = []
    monkeypatch.setattr(storage, "MEMORY_FILE", tmp_path / "memory.json")
    storage.get_user_data(commands.SPECIAL_USER_ID, "Owner")

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent_messages.append(content or "<embed>")

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

    for command_text in (
        f"/뇌추가 {commands.SPECIAL_USER_ID} 급할수록 짧고 확실한 답을 선호한다.",
        f"/뇌수정 {commands.SPECIAL_USER_ID} 1 급할수록 짧고 실행 가능한 답을 선호한다.",
        f"/뇌삭제 {commands.SPECIAL_USER_ID} 1",
    ):
        asyncio.run(
            commands.handle_mentioned_message(
                message=message,
                user_text=command_text,
                user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
                room_key="room-1",
                room_data={},
                client=client,
            )
        )

    user_memory = storage.load_memory()[str(commands.SPECIAL_USER_ID)]
    assert user_memory["brain_notes"] == []
    assert "1번에 저장했어" in sent_messages[0]
    assert "1번 평가를 고쳤어" in sent_messages[1]
    assert "1번 평가를 지웠어" in sent_messages[2]


def test_brain_command_requires_explicit_target(monkeypatch, tmp_path):
    sent_messages = []
    monkeypatch.setattr(storage, "MEMORY_FILE", tmp_path / "memory.json")

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent_messages.append(content or "<embed>")

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
            user_text="/뇌추가 급할수록 짧고 확실한 답을 선호한다.",
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert "대상 사용자를" in sent_messages[0] or "그 호칭으로 저장된 유저" in sent_messages[0]
    assert "brain_notes" not in storage.load_memory().get(str(commands.SPECIAL_USER_ID), {})


def test_brain_command_trusts_model_judgment_after_explicit_target(monkeypatch, tmp_path):
    sent_messages = []
    monkeypatch.setattr(storage, "MEMORY_FILE", tmp_path / "memory.json")
    storage.get_user_data(commands.SPECIAL_USER_ID, "Owner")

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent_messages.append(content or "<embed>")

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
            user_text=f"/뇌추가 {commands.SPECIAL_USER_ID} 오늘만 피곤해서 답이 느림",
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert "1번에 저장했어" in sent_messages[0]
    assert storage.load_memory()[str(commands.SPECIAL_USER_ID)]["brain_notes"] == ["오늘만 피곤해서 답이 느림"]


def test_affection_change_accepts_explicit_user_id(monkeypatch, tmp_path):
    sent_messages = []
    monkeypatch.setattr(storage, "MEMORY_FILE", tmp_path / "memory.json")
    storage.save_memory({
        "123456789012345": {
            "name": "Alice",
            "nickname": "새별",
            "affection": 50,
            "history": [],
            "brain_notes": [],
        }
    })

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent_messages.append(content or "<embed>")

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
            user_text="/호감도증감 123456789012345 2",
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert storage.load_memory()["123456789012345"]["affection"] == 52
    assert sent_messages == ["…Alice의 호감도를 +2만큼 조정했어. 지금은 52야."]


def test_attachment_context_skips_natural_summary_command(monkeypatch):
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
        return "파일 내용을 기준으로 요약했어."

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
            user_text="이 파일 요약해줘",
            user_data={"name": "Alice", "nickname": "Alice", "affection": 50},
            room_key="room-1",
            room_data={},
            client=client,
            attachment_context="[첨부 파일 내용]\n[파일: note.md]\n```text\nhello\n```",
        )
    )

    assert sent_messages == ["파일 내용을 기준으로 요약했어."]
    assert reply_kwargs["user_message"] == "이 파일 요약해줘"
    assert "note.md" in reply_kwargs["attachment_context"]


def test_poll_close_command_passes_user_text_to_poll_handler(monkeypatch):
    close_calls = []

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            raise AssertionError(f"unexpected message: {content}")

    async def fake_close_poll_from_command(message, client, user_text):
        close_calls.append(user_text)

    monkeypatch.setattr(commands, "close_poll_from_command", fake_close_poll_from_command)

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
            user_text="/투표마감 최근",
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert close_calls == ["/투표마감 최근"]


def test_memory_reset_targets_one_split_file_and_preserves_news(monkeypatch, tmp_path):
    sent_messages = []
    monkeypatch.setattr(storage, "MEMORY_FILE", tmp_path / "memory.json")
    storage.save_memory({
        "123": {"name": "Alice", "history": [{"role": "user", "content": "hello"}]},
        POLLS_KEY: {"poll-1": {"question": "Dinner?"}},
        DAILY_NEWS_KEY: {"topics": ["AI"], "subscribers": {"1": {"name": "Owner"}}},
    })

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent_messages.append(content or "<embed>")

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
            user_text="/메모리초기화 대화 확인",
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    data = storage.load_memory()
    assert sent_messages == ["…응. 대화 메모리 파일 `conversation_memory.json`을 비웠어."]
    assert "123" not in data
    assert data[POLLS_KEY]["poll-1"]["question"] == "Dinner?"
    assert data[DAILY_NEWS_KEY]["subscribers"]["1"]["name"] == "Owner"

