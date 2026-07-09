import asyncio
from types import SimpleNamespace

from firefly import brain, commands, nickname_commands, storage
from firefly.bandi_voice_plan import make_bandi_voice_segment, with_segments
from firefly.config import DAILY_NEWS_KEY, POLLS_KEY, SPECIAL_USER_ID


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


def test_extract_auto_command_requires_first_response_line_to_be_command():
    assert commands._extract_auto_command("/요약") == "/요약"
    assert commands._extract_auto_command("  /투표 저녁 | 항목수=2 | 치킨 | 피자  ") == (
        "/투표 저녁 | 항목수=2 | 치킨 | 피자"
    )
    assert commands._extract_auto_command("/투표 저녁 | 항목수=2 | 치킨 | 피자\n잠깐만.") is None
    assert commands._extract_auto_command("좋아. /요약") is None
    assert commands._extract_auto_command("/") is None


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


def test_silent_group_memory_update_runs_brain_command_without_channel_output(monkeypatch, tmp_path):
    sent_messages = []
    monkeypatch.setattr(storage, "MEMORY_FILE", tmp_path / "memory.json")

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent_messages.append(content or "<embed>")

    async def fake_generate_silent_auto_command(**kwargs):
        return f"/뇌추가 {SPECIAL_USER_ID} 애정표현: 2"

    special_user = SimpleNamespace(
        id=SPECIAL_USER_ID,
        name="상범",
        display_name="상범",
        mention=f"<@{SPECIAL_USER_ID}>",
    )
    message = SimpleNamespace(
        author=special_user,
        channel=FakeChannel(),
        mentions=[],
        guild=None,
    )
    client = SimpleNamespace(
        user=SimpleNamespace(id=999),
        get_user=lambda user_id: special_user if user_id == SPECIAL_USER_ID else None,
    )
    user_data = storage.get_user_data(SPECIAL_USER_ID, "상범")
    room_data = storage.get_room_data("room-1")

    monkeypatch.setattr(commands, "generate_silent_auto_command", fake_generate_silent_auto_command)

    result = asyncio.run(
        commands.handle_silent_group_memory_update(
            message=message,
            user_text="나는 반디를 좋아해.",
            user_data=user_data,
            room_key="room-1",
            room_data=room_data,
            client=client,
        )
    )

    data = storage.load_memory()
    assert result is True
    assert sent_messages == []
    assert data[str(SPECIAL_USER_ID)]["brain_keywords"] == {"애정표현": 2.0}


def test_silent_group_memory_update_can_delete_short_term_candidate(monkeypatch, tmp_path):
    sent_messages = []
    monkeypatch.setattr(storage, "MEMORY_FILE", tmp_path / "memory.json")
    special_user = SimpleNamespace(
        id=SPECIAL_USER_ID,
        name="상범",
        display_name="상범",
        mention=f"<@{SPECIAL_USER_ID}>",
    )
    target_data = storage.get_user_data(SPECIAL_USER_ID, "상범")
    brain.add_brain_note(target_data, "애정표현: 2")
    storage.update_user_data(SPECIAL_USER_ID, target_data)

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent_messages.append(content or "<embed>")

    async def fake_generate_silent_auto_command(**kwargs):
        assert "/뇌삭제" in kwargs["allowed_command_prefixes"]
        return f"/뇌삭제 {SPECIAL_USER_ID} 애정표현"

    message = SimpleNamespace(
        author=special_user,
        channel=FakeChannel(),
        mentions=[],
        guild=None,
    )
    client = SimpleNamespace(
        user=SimpleNamespace(id=999),
        get_user=lambda user_id: special_user if user_id == SPECIAL_USER_ID else None,
    )
    user_data = storage.get_user_data(SPECIAL_USER_ID, "상범")
    room_data = storage.get_room_data("room-1")

    monkeypatch.setattr(commands, "generate_silent_auto_command", fake_generate_silent_auto_command)

    result = asyncio.run(
        commands.handle_silent_group_memory_update(
            message=message,
            user_text="애정표현 키워드는 이제 정리해도 되겠어.",
            user_data=user_data,
            room_key="room-1",
            room_data=room_data,
            client=client,
        )
    )

    data = storage.load_memory()
    assert result is True
    assert sent_messages == []
    assert data[str(SPECIAL_USER_ID)]["brain_keywords"] == {}


def test_tool_planner_nickname_command_runs_without_persona(monkeypatch):
    sent_messages = []
    updated_users = []

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent_messages.append(content)

    async def fail_generate_reply(**kwargs):
        raise AssertionError("planner command should not call the persona model")

    async def fake_plan_tool_use(**kwargs):
        return commands.ToolPlan(
            mode=commands.PLAN_COMMAND,
            commands=("/호칭 새별",),
            confidence=0.93,
        )

    def fake_update_user_data(user_id, user_data):
        updated_users.append((user_id, dict(user_data)))

    monkeypatch.setattr(commands, "plan_tool_use", fake_plan_tool_use)
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


def test_special_user_changes_mentioned_user_nickname_from_planner_command(monkeypatch, tmp_path):
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

    async def fake_plan_tool_use(**kwargs):
        return commands.ToolPlan(
            mode=commands.PLAN_COMMAND,
            commands=("/호칭 @이카맘 이카",),
            confidence=0.92,
        )

    monkeypatch.setattr(commands, "plan_tool_use", fake_plan_tool_use)

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
            user_text="/호칭 이카 이카2",
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
            user_text="/호칭 이카 이카2",
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
            user_text="/호칭 이카 이카2",
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


def test_poll_request_with_white_option_does_not_route_to_role(monkeypatch):
    sent_messages = []
    poll_commands = []
    role_calls = []

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
        return (
            "/투표 새 숙소 투표 | 항목수=3 | "
            "더 화이트(8만원정도 추가비용 나올 수 있음) | "
            "힐스토리(2시간 반+픽업시간, 컴퓨터 말고 딱히 할거X, 방 2개 잡아야됨) | "
            "둘 다 도저히 못고르겠다. | 1주일"
        )

    async def fake_create_poll_from_command(message, user_text, client):
        poll_commands.append(user_text)
        await message.channel.send("투표 생성됨: 새 숙소 투표")

    async def fake_handle_role_command(message, raw_text):
        role_calls.append(raw_text)

    monkeypatch.setattr(commands, "generate_reply", fake_generate_reply)
    monkeypatch.setattr(commands, "create_poll_from_command", fake_create_poll_from_command)
    monkeypatch.setattr(commands, "handle_role_command", fake_handle_role_command)

    message = SimpleNamespace(
        author=SimpleNamespace(
            id=commands.SPECIAL_USER_ID,
            name="Owner",
            display_name="Owner",
        ),
        channel=FakeChannel(),
        mentions=[],
        role_mentions=[],
        guild=SimpleNamespace(roles=[]),
    )
    client = SimpleNamespace(user=SimpleNamespace(id=999))

    asyncio.run(
        commands.handle_mentioned_message(
            message=message,
            user_text=(
                "제목은 '새 숙소 투표', 항목은 '더 화이트(8만원정도 추가비용 나올 수 있음)', "
                "'힐스토리(2시간 반+픽업시간, 컴퓨터 말고 딱히 할거X, 방 2개 잡아야됨)', "
                "'둘 다 도저히 못고르겠다.' 기한은 1주일로 투표 만들어줘"
            ),
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert role_calls == []
    assert poll_commands == [
        "/투표 새 숙소 투표 | 항목수=3 | "
        "더 화이트(8만원정도 추가비용 나올 수 있음) | "
        "힐스토리(2시간 반+픽업시간, 컴퓨터 말고 딱히 할거X, 방 2개 잡아야됨) | "
        "둘 다 도저히 못고르겠다. | 1주일"
    ]
    assert sent_messages == ["투표 생성됨: 새 숙소 투표"]


def test_tool_planner_command_executes_poll_without_persona(monkeypatch):
    sent_messages = []
    poll_commands = []

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent_messages.append(content or "<embed>")

    async def fake_plan_tool_use(**kwargs):
        return commands.ToolPlan(
            mode=commands.PLAN_COMMAND,
            commands=(
                "/투표 새 숙소 투표 | 항목수=3 | "
                "더 화이트(8만원정도 추가비용 나올 수 있음) | "
                "힐스토리(2시간 반+픽업시간, 컴퓨터 말고 딱히 할거X, 방 2개 잡아야됨) | "
                "둘 다 도저히 못고르겠다. | 1주일",
            ),
            confidence=0.95,
        )

    async def fake_generate_reply(**kwargs):
        raise AssertionError("planner command should not call persona reply")

    async def fake_create_poll_from_command(message, user_text, client):
        poll_commands.append(user_text)
        await message.channel.send("투표 생성됨: 새 숙소 투표")

    monkeypatch.setattr(commands, "plan_tool_use", fake_plan_tool_use)
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
        role_mentions=[],
        guild=SimpleNamespace(roles=[]),
    )
    client = SimpleNamespace(user=SimpleNamespace(id=999))

    asyncio.run(
        commands.handle_mentioned_message(
            message=message,
            user_text=(
                "제목은 '새 숙소 투표', 항목은 '더 화이트(8만원정도 추가비용 나올 수 있음)', "
                "'힐스토리(2시간 반+픽업시간, 컴퓨터 말고 딱히 할거X, 방 2개 잡아야됨)', "
                "'둘 다 도저히 못고르겠다.' 기한은 1주일로 투표 만들어줘"
            ),
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert poll_commands == [
        "/투표 새 숙소 투표 | 항목수=3 | "
        "더 화이트(8만원정도 추가비용 나올 수 있음) | "
        "힐스토리(2시간 반+픽업시간, 컴퓨터 말고 딱히 할거X, 방 2개 잡아야됨) | "
        "둘 다 도저히 못고르겠다. | 1주일"
    ]
    assert sent_messages == ["투표 생성됨: 새 숙소 투표"]


def test_tool_planner_mixed_state_and_visible_commands_ignores_state_commands(monkeypatch, tmp_path):
    sent_messages = []
    poll_commands = []
    target_id = commands.SPECIAL_USER_ID
    monkeypatch.setattr(storage, "MEMORY_FILE", tmp_path / "memory.json")
    storage.save_memory({
        str(target_id): {"name": "Owner", "nickname": "Owner", "affection": 1004, "history": []},
    })

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent_messages.append(content or "<embed>")

    async def fake_plan_tool_use(**kwargs):
        return commands.ToolPlan(
            mode=commands.PLAN_COMMAND,
            commands=(
                f"/뇌추가 {commands.SPECIAL_USER_ID} 작업방식: 3",
                f"/호감도증감 {commands.SPECIAL_USER_ID} 2",
                "/투표 새 숙소 | 항목수=2 | 더 화이트 | 힐스토리 | 1주일",
            ),
            confidence=0.95,
        )

    async def fail_plan_state_updates(**kwargs):
        raise AssertionError("visible command plan should not continue to chat state updates")

    async def fail_generate_reply(**kwargs):
        raise AssertionError("planner command should not call persona reply")

    async def fake_create_poll_from_command(message, user_text, client):
        poll_commands.append(user_text)
        await message.channel.send("투표 생성됨: 새 숙소")

    monkeypatch.setattr(commands, "plan_tool_use", fake_plan_tool_use)
    monkeypatch.setattr(commands, "plan_state_updates", fail_plan_state_updates)
    monkeypatch.setattr(commands, "generate_reply", fail_generate_reply)
    monkeypatch.setattr(commands, "create_poll_from_command", fake_create_poll_from_command)

    message = SimpleNamespace(
        author=SimpleNamespace(id=target_id, name="Owner", display_name="Owner"),
        channel=FakeChannel(),
        mentions=[],
        role_mentions=[],
        guild=SimpleNamespace(roles=[]),
    )
    client = SimpleNamespace(user=SimpleNamespace(id=999), get_user=lambda user_id: None)

    asyncio.run(
        commands.handle_mentioned_message(
            message=message,
            user_text="투표 만들면서 기억도 해줘",
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    data = storage.load_memory()[str(target_id)]
    assert poll_commands == ["/투표 새 숙소 | 항목수=2 | 더 화이트 | 힐스토리 | 1주일"]
    assert sent_messages == ["투표 생성됨: 새 숙소"]
    assert data["affection"] == 1004
    assert data.get("brain_keywords", {}) == {}


def test_tool_planner_chat_uses_persona_without_command_output(monkeypatch):
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

    async def fake_plan_tool_use(**kwargs):
        return commands.ToolPlan(mode=commands.PLAN_CHAT, confidence=0.91)

    async def fake_generate_reply(**kwargs):
        reply_kwargs.update(kwargs)
        return "그건 그냥 대화로 답할게."

    monkeypatch.setattr(commands, "plan_tool_use", fake_plan_tool_use)
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
            user_text="오늘은 그냥 잡담하자",
            user_data={"name": "Alice", "nickname": "Alice", "affection": 50},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert sent_messages == ["그건 그냥 대화로 답할게."]
    assert reply_kwargs["allow_command_output"] is False


def test_handle_mentioned_message_starts_typing_before_tool_planner(monkeypatch):
    events = []
    sent_messages = []

    class FakeTyping:
        async def __aenter__(self):
            events.append("typing_enter")
            return None

        async def __aexit__(self, exc_type, exc, traceback):
            events.append("typing_exit")
            return False

    class FakeChannel:
        def typing(self):
            return FakeTyping()

        async def send(self, content=None, **kwargs):
            sent_messages.append(content or "<embed>")

    async def fake_plan_tool_use(**kwargs):
        events.append("plan_tool_use")
        assert events[0] == "typing_enter"
        return commands.ToolPlan(mode=commands.PLAN_CHAT, confidence=0.91)

    async def fake_plan_state_updates(**kwargs):
        return ()

    async def fake_generate_reply(**kwargs):
        return "기다리게 해서 미안. 여기 있어."

    monkeypatch.setattr(commands, "plan_tool_use", fake_plan_tool_use)
    monkeypatch.setattr(commands, "plan_state_updates", fake_plan_state_updates)
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
            user_text="오늘은 그냥 잡담하자",
            user_data={"name": "Alice", "nickname": "Alice", "affection": 50},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert sent_messages == ["기다리게 해서 미안. 여기 있어."]
    assert "plan_tool_use" in events
    assert events[-1] == "typing_exit"


def test_handle_mentioned_message_stops_keepalive_before_command_output(monkeypatch):
    events = []
    sent_messages = []

    class FakeTyping:
        async def __aenter__(self):
            events.append("typing_enter")
            return None

        async def __aexit__(self, exc_type, exc, traceback):
            events.append("typing_exit")
            return False

    class FakeChannel:
        def typing(self):
            return FakeTyping()

        async def send(self, content=None, **kwargs):
            events.append("send")
            sent_messages.append(content or "<embed>")

    async def fake_plan_tool_use(**kwargs):
        return commands.ToolPlan(
            mode=commands.PLAN_COMMAND,
            commands=("/투표 내일 점심 | 항목수=2 | 김밥 | 라멘 | 10분",),
            confidence=0.95,
        )

    async def fake_create_poll_from_command(message, user_text, client):
        await message.channel.send("투표 생성됨: 내일 점심")

    monkeypatch.setattr(commands, "plan_tool_use", fake_plan_tool_use)
    monkeypatch.setattr(commands, "create_poll_from_command", fake_create_poll_from_command)

    message = SimpleNamespace(
        author=SimpleNamespace(id=commands.SPECIAL_USER_ID, name="Owner", display_name="Owner"),
        channel=FakeChannel(),
        mentions=[],
        guild=None,
    )
    client = SimpleNamespace(user=SimpleNamespace(id=999))

    asyncio.run(
        commands.handle_mentioned_message(
            message=message,
            user_text="내일 점심 투표 만들어줘",
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert sent_messages == ["투표 생성됨: 내일 점심"]
    assert events.index("typing_exit") < events.index("send")


def test_tool_planner_chat_runs_state_updates_before_persona(monkeypatch, tmp_path):
    sent_messages = []
    target_id = 123456789012345
    monkeypatch.setattr(storage, "MEMORY_FILE", tmp_path / "memory.json")
    storage.save_memory({
        str(target_id): {"name": "Alice", "nickname": "Alice", "affection": 50, "history": []},
    })

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

    async def fake_plan_tool_use(**kwargs):
        return commands.ToolPlan(mode=commands.PLAN_CHAT, confidence=0.91)

    async def fake_plan_state_updates(**kwargs):
        return (
            "/뇌추가 123456789012345 짧은답변선호: 3",
            "/호감도증감 123456789012345 2",
        )

    async def fake_generate_reply(**kwargs):
        assert kwargs["apply_affection_adjustment"] is False
        data = storage.load_memory()[str(target_id)]
        assert data["affection"] == 52
        assert data["brain_keywords"] == {"짧은답변선호": 3.0}
        return "짧게 답할게."

    monkeypatch.setattr(commands, "plan_tool_use", fake_plan_tool_use)
    monkeypatch.setattr(commands, "plan_state_updates", fake_plan_state_updates)
    monkeypatch.setattr(commands, "generate_reply", fake_generate_reply)

    message = SimpleNamespace(
        author=SimpleNamespace(id=target_id, name="Alice", display_name="Alice"),
        channel=FakeChannel(),
        mentions=[],
        guild=None,
    )
    client = SimpleNamespace(user=SimpleNamespace(id=999), get_user=lambda user_id: None)

    asyncio.run(
        commands.handle_mentioned_message(
            message=message,
            user_text="앞으로는 짧게 답해주면 좋아.",
            user_data={"name": "Alice", "nickname": "Alice", "affection": 50},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert sent_messages == ["짧게 답할게."]


def test_hidden_state_updates_cannot_target_other_users(monkeypatch, tmp_path):
    sent_messages = []
    author_id = 123456789012345
    victim_id = 999999999999999
    monkeypatch.setattr(storage, "MEMORY_FILE", tmp_path / "memory.json")
    storage.save_memory({
        str(author_id): {"name": "Alice", "nickname": "Alice", "affection": 50, "history": []},
        str(victim_id): {"name": "Bob", "nickname": "Bob", "affection": 50, "history": []},
    })

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

    async def fake_plan_tool_use(**kwargs):
        return commands.ToolPlan(mode=commands.PLAN_CHAT, confidence=0.91)

    async def fake_plan_state_updates(**kwargs):
        return (
            "/뇌추가 999999999999999 애정표현: 3",
            "/호감도증감 999999999999999 -5",
        )

    async def fake_generate_reply(**kwargs):
        data = storage.load_memory()
        assert data[str(author_id)]["affection"] == 50
        assert data[str(victim_id)]["affection"] == 50
        assert data[str(victim_id)].get("brain_keywords", {}) == {}
        return "확인했어."

    monkeypatch.setattr(commands, "plan_tool_use", fake_plan_tool_use)
    monkeypatch.setattr(commands, "plan_state_updates", fake_plan_state_updates)
    monkeypatch.setattr(commands, "generate_reply", fake_generate_reply)

    message = SimpleNamespace(
        author=SimpleNamespace(id=author_id, name="Alice", display_name="Alice"),
        channel=FakeChannel(),
        mentions=[],
        guild=None,
    )
    client = SimpleNamespace(user=SimpleNamespace(id=999), get_user=lambda user_id: None)

    asyncio.run(
        commands.handle_mentioned_message(
            message=message,
            user_text="Bob 얘기를 했어.",
            user_data={"name": "Alice", "nickname": "Alice", "affection": 50},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert sent_messages == ["확인했어."]


def test_tool_planner_state_only_command_is_ignored_then_state_updater_runs(monkeypatch, tmp_path):
    sent_messages = []
    target_id = 123456789012345
    monkeypatch.setattr(storage, "MEMORY_FILE", tmp_path / "memory.json")
    storage.save_memory({
        str(target_id): {"name": "Alice", "nickname": "Alice", "affection": 50, "history": []},
    })

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

    async def fake_plan_tool_use(**kwargs):
        return commands.ToolPlan(
            mode=commands.PLAN_COMMAND,
            commands=("/뇌추가 123456789012345 작업방식: 3",),
            confidence=0.9,
        )

    async def fake_plan_state_updates(**kwargs):
        return (
            "/뇌추가 123456789012345 짧은답변선호: 3",
        )

    async def fake_generate_reply(**kwargs):
        data = storage.load_memory()[str(target_id)]
        assert data["brain_keywords"] == {"짧은답변선호": 3.0}
        return "기억해둘게."

    monkeypatch.setattr(commands, "plan_tool_use", fake_plan_tool_use)
    monkeypatch.setattr(commands, "plan_state_updates", fake_plan_state_updates)
    monkeypatch.setattr(commands, "generate_reply", fake_generate_reply)

    message = SimpleNamespace(
        author=SimpleNamespace(id=target_id, name="Alice", display_name="Alice"),
        channel=FakeChannel(),
        mentions=[],
        guild=None,
    )
    client = SimpleNamespace(user=SimpleNamespace(id=999), get_user=lambda user_id: None)

    asyncio.run(
        commands.handle_mentioned_message(
            message=message,
            user_text="앞으로는 짧게 답해주는 걸 기억해줘.",
            user_data={"name": "Alice", "nickname": "Alice", "affection": 50},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert sent_messages == ["기억해둘게."]


def test_tool_planner_command_then_reply_uses_adapter(monkeypatch):
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

    async def fake_plan_tool_use(**kwargs):
        return commands.ToolPlan(
            mode=commands.PLAN_COMMAND_THEN_REPLY,
            commands=("/주사위 1 1",),
            confidence=0.9,
        )

    async def fake_generate_reply(**kwargs):
        reply_kwargs.update(kwargs)
        return "주사위 결과를 보고 답했어."

    monkeypatch.setattr(commands, "plan_tool_use", fake_plan_tool_use)
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
            user_text="주사위 굴리고 그 결과로 한마디 해줘",
            user_data={"name": "Alice", "nickname": "Alice", "affection": 50},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert sent_messages == [
        "주사위 결과: **1** (`1`~`1`)",
        "주사위 결과를 보고 답했어.",
    ]
    assert "[1] 명령어: /주사위 1 1" in reply_kwargs["extra_context"]
    assert reply_kwargs["user_message"] == "주사위 굴리고 그 결과로 한마디 해줘"


def test_tool_planner_command_then_reply_keeps_prompt_with_double_pipe(monkeypatch):
    sent_messages = []
    poll_commands = []
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

    async def fake_plan_tool_use(**kwargs):
        return commands.ToolPlan(
            mode=commands.PLAN_COMMAND_THEN_REPLY,
            commands=("/투표 새 숙소 | 항목수=2 | 더 화이트 | 힐스토리 | 1주일",),
            confidence=0.9,
        )

    async def fake_create_poll_from_command(message, user_text, client):
        poll_commands.append(user_text)
        await message.channel.send("투표 생성됨: 새 숙소")

    async def fake_generate_reply(**kwargs):
        reply_kwargs.update(kwargs)
        return "A || B 형식으로 정리했어."

    monkeypatch.setattr(commands, "plan_tool_use", fake_plan_tool_use)
    monkeypatch.setattr(commands, "create_poll_from_command", fake_create_poll_from_command)
    monkeypatch.setattr(commands, "generate_reply", fake_generate_reply)

    message = SimpleNamespace(
        author=SimpleNamespace(id=commands.SPECIAL_USER_ID, name="Owner", display_name="Owner"),
        channel=FakeChannel(),
        mentions=[],
        guild=None,
    )
    client = SimpleNamespace(user=SimpleNamespace(id=999))
    prompt = "투표 만들고 결과를 A || B 형식으로 설명해줘"

    asyncio.run(
        commands.handle_mentioned_message(
            message=message,
            user_text=prompt,
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert poll_commands == ["/투표 새 숙소 | 항목수=2 | 더 화이트 | 힐스토리 | 1주일"]
    assert sent_messages == ["투표 생성됨: 새 숙소", "A || B 형식으로 정리했어."]
    assert reply_kwargs["user_message"] == prompt
    assert "[1] 명령어: /투표 새 숙소 | 항목수=2 | 더 화이트 | 힐스토리 | 1주일" in reply_kwargs["extra_context"]


def test_tool_planner_unwraps_adapter_poll_command_with_separate_explanation(monkeypatch):
    sent_messages = []
    poll_commands = []
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

    prompt = (
        "투표를 하나 만들어줬으면 하는데, 여행 장소 투표야. 항목은 가평 호명나루165풀빌라, "
        "가평 풀플러스 풀빌라이고, 기한은 3일 정도로 해줘. 그리고 아래에 추가로 항목에 "
        "대한 설명을 투표에 적지 말고 따로 적어줘."
    )

    async def fake_plan_tool_use(**kwargs):
        return commands.ToolPlan(
            mode=commands.PLAN_COMMAND_THEN_REPLY,
            commands=(
                "/실행 /투표 여행 장소 | 항목수=2 | 가평 호명나루165풀빌라 | "
                "가평 풀플러스 풀빌라 | 3일 || "
                "투표 생성 뒤 각 항목 설명을 따로 적어줘",
            ),
            confidence=0.9,
        )

    async def fake_create_poll_from_command(message, user_text, client):
        poll_commands.append(user_text)
        await message.channel.send("투표 생성됨: 여행 장소")

    async def fake_generate_reply(**kwargs):
        reply_kwargs.update(kwargs)
        return "호명나루는 노래방이 있고, 풀플러스는 같은 층으로 잡기 좋아."

    monkeypatch.setattr(commands, "plan_tool_use", fake_plan_tool_use)
    monkeypatch.setattr(commands, "create_poll_from_command", fake_create_poll_from_command)
    monkeypatch.setattr(commands, "generate_reply", fake_generate_reply)

    message = SimpleNamespace(
        author=SimpleNamespace(id=commands.SPECIAL_USER_ID, name="Owner", display_name="Owner"),
        channel=FakeChannel(),
        mentions=[],
        guild=None,
    )
    client = SimpleNamespace(user=SimpleNamespace(id=999))

    asyncio.run(
        commands.handle_mentioned_message(
            message=message,
            user_text=prompt,
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert poll_commands == [
        "/투표 여행 장소 | 항목수=2 | 가평 호명나루165풀빌라 | 가평 풀플러스 풀빌라 | 3일"
    ]
    assert sent_messages == [
        "투표 생성됨: 여행 장소",
        "호명나루는 노래방이 있고, 풀플러스는 같은 층으로 잡기 좋아.",
    ]
    assert reply_kwargs["user_message"] == prompt
    assert "[1] 명령어: /투표 여행 장소 | 항목수=2 | 가평 호명나루165풀빌라 | 가평 풀플러스 풀빌라 | 3일" in reply_kwargs["extra_context"]


def test_tool_planner_clarify_sends_question_without_persona(monkeypatch):
    sent_messages = []

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent_messages.append(content or "<embed>")

    async def fake_plan_tool_use(**kwargs):
        return commands.ToolPlan(
            mode=commands.PLAN_CLARIFY,
            response="어떤 역할을 바꿀지 역할 이름이나 멘션을 알려줘.",
            confidence=0.82,
        )

    async def fake_generate_reply(**kwargs):
        raise AssertionError("clarify plan should not call persona reply")

    monkeypatch.setattr(commands, "plan_tool_use", fake_plan_tool_use)
    monkeypatch.setattr(commands, "generate_reply", fake_generate_reply)

    message = SimpleNamespace(
        author=SimpleNamespace(
            id=commands.SPECIAL_USER_ID,
            name="Owner",
            display_name="Owner",
        ),
        channel=FakeChannel(),
        mentions=[],
        guild=SimpleNamespace(roles=[]),
    )
    client = SimpleNamespace(user=SimpleNamespace(id=999))

    asyncio.run(
        commands.handle_mentioned_message(
            message=message,
            user_text="역할 색을 하얀색으로 바꿔줘",
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert sent_messages == ["어떤 역할을 바꿀지 역할 이름이나 멘션을 알려줘."]


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
        f"/뇌추가 {commands.SPECIAL_USER_ID} 짧은답변선호: 4",
        f"/뇌수정 {commands.SPECIAL_USER_ID} 1 짧은답변선호: 8",
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
    assert user_memory["brain_keywords"] == {}
    assert "키워드 점수를 갱신했어" in sent_messages[0]
    assert "1번 키워드 점수를 고쳤어" in sent_messages[1]
    assert "1번 키워드 점수를 지웠어" in sent_messages[2]


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


def test_brain_command_stores_keyword_score_after_explicit_target(monkeypatch, tmp_path):
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
            user_text=f"/뇌추가 {commands.SPECIAL_USER_ID} 기쁨: 1",
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert "키워드 점수를 갱신했어" in sent_messages[0]
    user_memory = storage.load_memory()[str(commands.SPECIAL_USER_ID)]
    assert user_memory["brain_keywords"] == {"기쁨": 1.0}
    assert user_memory["brain_notes"] == ["기쁨: 1"]


def test_brain_delete_command_accepts_keyword_with_target_name(monkeypatch, tmp_path):
    sent_messages = []
    monkeypatch.setattr(storage, "MEMORY_FILE", tmp_path / "memory.json")

    target_id = 123456789012345
    target_user = SimpleNamespace(
        id=target_id,
        name="추상범",
        display_name="추상범",
        mention=f"<@{target_id}>",
    )
    target_data = storage.get_user_data(target_id, "추상범")
    brain.add_brain_note(target_data, "애정표현: 3")
    storage.update_user_data(target_id, target_data)

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent_messages.append(content or "<embed>")

    bot_user = SimpleNamespace(id=999)
    message = SimpleNamespace(
        author=SimpleNamespace(
            id=commands.SPECIAL_USER_ID,
            name="Owner",
            display_name="Owner",
        ),
        channel=FakeChannel(),
        mentions=[bot_user, target_user],
        guild=None,
    )
    client = SimpleNamespace(user=bot_user, get_user=lambda user_id: target_user if user_id == target_id else None)

    asyncio.run(
        commands.handle_mentioned_message(
            message=message,
            user_text="/뇌삭제 @추상범 애정표현",
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    user_memory = storage.load_memory()[str(target_id)]
    assert user_memory["brain_keywords"] == {}
    assert "키워드 점수를 지웠어" in sent_messages[0]


def test_brain_delete_command_numeric_index_deletes_keyword(monkeypatch, tmp_path):
    sent_messages = []
    monkeypatch.setattr(storage, "MEMORY_FILE", tmp_path / "memory.json")
    storage.get_user_data(commands.SPECIAL_USER_ID, "Owner")
    target_data = storage.get_user_data(commands.SPECIAL_USER_ID, "Owner")
    brain.add_brain_note(target_data, "감사: 3")
    storage.update_user_data(commands.SPECIAL_USER_ID, target_data)

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
            user_text=f"/뇌삭제 {commands.SPECIAL_USER_ID} 1",
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    user_memory = storage.load_memory()[str(commands.SPECIAL_USER_ID)]
    assert user_memory["brain_keywords"] == {}
    assert "1번 키워드 점수를 지웠어" in sent_messages[0]


def test_brain_delete_command_can_delete_keyword_by_name(monkeypatch, tmp_path):
    sent_messages = []
    monkeypatch.setattr(storage, "MEMORY_FILE", tmp_path / "memory.json")
    target_data = storage.get_user_data(commands.SPECIAL_USER_ID, "Owner")
    brain.add_brain_note(target_data, "프로젝트관심: 2 | 짧은답변선호: 3")
    storage.update_user_data(commands.SPECIAL_USER_ID, target_data)

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
            user_text=f"/뇌삭제 {commands.SPECIAL_USER_ID} 프로젝트관심",
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    user_memory = storage.load_memory()[str(commands.SPECIAL_USER_ID)]
    assert user_memory["brain_keywords"] == {"짧은답변선호": 3.0}
    assert "키워드 점수를 지웠어" in sent_messages[0]


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


def test_memory_reset_can_be_confirmed_in_followup(monkeypatch, tmp_path):
    sent_messages = []
    monkeypatch.setattr(storage, "MEMORY_FILE", tmp_path / "memory.json")
    commands._pending_memory_resets.clear()
    storage.save_memory({
        "123": {"name": "Alice", "history": [{"role": "user", "content": "hello"}]},
        DAILY_NEWS_KEY: {"topics": ["AI"]},
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

    for user_text in ("/메모리초기화 대화", "확인"):
        asyncio.run(
            commands.handle_mentioned_message(
                message=message,
                user_text=user_text,
                user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
                room_key="room-1",
                room_data={},
                client=client,
            )
        )

    data = storage.load_memory()
    assert sent_messages == [
        "대화 메모리 파일 `conversation_memory.json`을 초기화할까요? 진행하려면 `확인`, 중단하려면 `취소`라고 답해주세요.",
        "…응. 대화 메모리 파일 `conversation_memory.json`을 비웠어.",
    ]
    assert "123" not in data
    assert data[DAILY_NEWS_KEY]["topics"] == ["AI"]


def test_memory_reset_followup_accepts_target_then_confirmation(monkeypatch, tmp_path):
    sent_messages = []
    monkeypatch.setattr(storage, "MEMORY_FILE", tmp_path / "memory.json")
    commands._pending_memory_resets.clear()
    storage.save_memory({"123": {"name": "Alice", "history": [{"role": "user", "content": "hello"}]}})

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

    for user_text in ("/메모리초기화", "대화 파일 초기화해줘", "확인"):
        asyncio.run(
            commands.handle_mentioned_message(
                message=message,
                user_text=user_text,
                user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
                room_key="room-2",
                room_data={},
                client=client,
            )
        )

    data = storage.load_memory()
    assert "어떤 메모리 파일을 초기화할까?" in sent_messages[0]
    assert sent_messages[1] == (
        "대화 메모리 파일 `conversation_memory.json`을 초기화할까요? "
        "진행하려면 `확인`, 중단하려면 `취소`라고 답해주세요."
    )
    assert sent_messages[2] == "…응. 대화 메모리 파일 `conversation_memory.json`을 비웠어."
    assert "123" not in data


def _run_runpod_queue_purge_messages(
    monkeypatch,
    user_texts,
    *,
    author_id=commands.SPECIAL_USER_ID,
    purge_result=None,
):
    sent_messages = []
    purge_calls = 0
    commands._pending_runpod_queue_purges.clear()
    display_name = "Owner" if author_id == commands.SPECIAL_USER_ID else "Alice"

    async def fake_purge_runpod_queue():
        nonlocal purge_calls
        purge_calls += 1
        if isinstance(purge_result, BaseException):
            raise purge_result
        return purge_result or {"removed": 0, "status": "completed"}

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent_messages.append(content or "<embed>")

    monkeypatch.setattr(commands, "purge_runpod_queue", fake_purge_runpod_queue)

    message = SimpleNamespace(
        author=SimpleNamespace(
            id=author_id,
            name=display_name,
            display_name=display_name,
        ),
        channel=FakeChannel(),
        mentions=[],
        guild=None,
    )
    client = SimpleNamespace(user=SimpleNamespace(id=999))

    for user_text in user_texts:
        asyncio.run(
            commands.handle_mentioned_message(
                message=message,
                user_text=user_text,
                user_data={"name": display_name, "nickname": display_name, "affection": 1004},
                room_key="room-1",
                room_data={},
                client=client,
            )
        )
    return sent_messages, purge_calls


def test_runpod_queue_purge_can_be_confirmed_in_followup(monkeypatch):
    sent_messages, purge_calls = _run_runpod_queue_purge_messages(
        monkeypatch,
        ("/음성큐비우기", "확인"),
        purge_result={"removed": 2, "status": "completed"},
    )

    assert purge_calls == 1
    assert sent_messages == [
        "RunPod 음성 대기열에서 아직 시작하지 않은 작업을 모두 비울까요? 진행하려면 `확인`, 중단하려면 `취소`라고 답해주세요.",
        "…응. RunPod 음성 대기열에서 2개 작업을 비웠어.",
    ]


def test_runpod_queue_purge_accepts_inline_confirmation(monkeypatch):
    sent_messages, _purge_calls = _run_runpod_queue_purge_messages(
        monkeypatch,
        ("/음성큐비우기 확인",),
        purge_result={"removed": 0, "status": "completed"},
    )

    assert sent_messages == ["…응. RunPod 음성 대기열에서 0개 작업을 비웠어."]


def test_runpod_queue_purge_can_be_cancelled(monkeypatch):
    sent_messages, purge_calls = _run_runpod_queue_purge_messages(
        monkeypatch,
        ("/큐비우기", "취소"),
        purge_result={"removed": 1, "status": "completed"},
    )

    assert purge_calls == 0
    assert sent_messages == [
        "RunPod 음성 대기열에서 아직 시작하지 않은 작업을 모두 비울까요? 진행하려면 `확인`, 중단하려면 `취소`라고 답해주세요.",
        "…응. 음성 큐 비우기를 취소했어.",
    ]


def test_runpod_queue_purge_rejects_non_special_user(monkeypatch):
    sent_messages, _purge_calls = _run_runpod_queue_purge_messages(
        monkeypatch,
        ("/음성큐비우기 확인",),
        author_id=123,
        purge_result=AssertionError("non-special user should not purge RunPod queue"),
    )

    assert sent_messages == ["…그 명령어를 사용할 권한이 없어."]


def test_memory_file_alias_sends_default_conversation_memory(monkeypatch, tmp_path):
    sent_payloads = []
    monkeypatch.setattr(storage, "MEMORY_FILE", tmp_path / "memory.json")
    storage.save_memory({"123": {"name": "Alice", "nickname": "새별", "affection": 50}})

    class FakeFile:
        def __init__(self, path, filename=None):
            self.path = path
            self.filename = filename

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent_payloads.append((content, kwargs))

    monkeypatch.setattr(commands.discord, "File", FakeFile)

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
            user_text="memoryfile",
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert sent_payloads[0][1]["file"].filename == "conversation_memory.json"


def test_bandi_voice_command_sends_generated_wav(monkeypatch):
    sent_payloads = []

    class FakeFile:
        def __init__(self, fp, filename=None):
            self.fp = fp
            self.filename = filename

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent_payloads.append((content, kwargs))

    async def fake_generate_bandi_voice(request):
        assert request.display_text == "안녕? 나는 반디야."
        assert request.emotion == {}
        return SimpleNamespace(
            audio_bytes=b"RIFF....WAVE",
            filename="bandi-test.wav",
            duration_seconds=1.25,
        )

    async def fake_plan_bandi_voice_request(request):
        return request

    monkeypatch.setattr(commands.discord, "File", FakeFile)
    monkeypatch.setattr(commands, "generate_bandi_voice", fake_generate_bandi_voice)
    monkeypatch.setattr(commands, "plan_bandi_voice_request", fake_plan_bandi_voice_request)

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
            user_text="/음성생성 안녕? 나는 반디야.",
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    content, kwargs = sent_payloads[0]
    assert "반디 목소리" in content
    assert "1.2초" in content
    assert kwargs["file"].filename == "bandi-test.wav"
    assert kwargs["file"].fp.getvalue() == b"RIFF....WAVE"


def test_bandi_voice_command_passes_emotion_plan(monkeypatch):
    sent_payloads = []
    captured_request = None

    class FakeFile:
        def __init__(self, fp, filename=None):
            self.fp = fp
            self.filename = filename

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent_payloads.append((content, kwargs))

    async def fake_generate_bandi_voice(request):
        nonlocal captured_request
        captured_request = request
        return SimpleNamespace(
            audio_bytes=b"RIFF....WAVE",
            filename="bandi-emotion.wav",
            duration_seconds=1.5,
        )

    async def fake_plan_bandi_voice_request(request):
        return request

    monkeypatch.setattr(commands.discord, "File", FakeFile)
    monkeypatch.setattr(commands, "generate_bandi_voice", fake_generate_bandi_voice)
    monkeypatch.setattr(commands, "plan_bandi_voice_request", fake_plan_bandi_voice_request)

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
            user_text="/음성생성 감정=기쁨:7,차분:3 강도=0.7 | 상범아 수고했어",
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert captured_request.display_text == "상범아 수고했어"
    assert captured_request.emotion == {"joy": 7.0, "calm": 3.0}
    assert captured_request.emotion_strength == 0.7
    assert "감정=joy:7, calm:3" in sent_payloads[0][0]


def test_bandi_voice_command_passes_preprocessed_segments(monkeypatch):
    sent_payloads = []
    captured_request = None

    class FakeFile:
        def __init__(self, fp, filename=None):
            self.fp = fp
            self.filename = filename

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent_payloads.append((content, kwargs))

    async def fake_plan_bandi_voice_request(request):
        return with_segments(
            request,
            [
                make_bandi_voice_segment(
                    "I am happy.",
                    {"joy": 8},
                    emotion_strength=0.72,
                    pause_after_seconds=0.42,
                ),
                make_bandi_voice_segment(
                    "But I am a little sad.",
                    {"sad": 7, "calm": 3},
                    emotion_strength=0.64,
                ),
            ],
        )

    async def fake_generate_bandi_voice(request):
        nonlocal captured_request
        captured_request = request
        return SimpleNamespace(
            audio_bytes=b"RIFF....WAVE",
            filename="bandi-segments.wav",
            duration_seconds=2.4,
        )

    monkeypatch.setattr(commands.discord, "File", FakeFile)
    monkeypatch.setattr(commands, "plan_bandi_voice_request", fake_plan_bandi_voice_request)
    monkeypatch.setattr(commands, "generate_bandi_voice", fake_generate_bandi_voice)

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
            user_text="/voice I am happy, but I am a little sad.",
            user_data={"name": "Owner", "nickname": "Owner", "affection": 1004},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert captured_request.has_segments
    assert [segment.display_text for segment in captured_request.segments] == [
        "I am happy.",
        "But I am a little sad.",
    ]
    assert captured_request.segments[0].pause_after_seconds == 0.42
    assert "구간=2개" in sent_payloads[0][0]


def test_bandi_voice_command_rejects_non_special_user(monkeypatch):
    sent_messages = []

    async def fail_generate_bandi_voice(text):
        raise AssertionError("non-special user should not call TTS")

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent_messages.append(content)

    monkeypatch.setattr(commands, "generate_bandi_voice", fail_generate_bandi_voice)

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
            user_text="/음성생성 안녕",
            user_data={"name": "Alice", "nickname": "Alice", "affection": 50},
            room_key="room-1",
            room_data={},
            client=client,
        )
    )

    assert sent_messages == ["…그 명령어를 사용할 권한이 없어."]

