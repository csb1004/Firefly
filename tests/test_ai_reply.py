import asyncio
from types import SimpleNamespace

from firefly import ai, storage
from firefly.config import ROOMS_KEY, SPECIAL_USER_ID


def _use_temp_memory(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "MEMORY_FILE", tmp_path / "memory.json")
    monkeypatch.setattr(ai, "get_current_time_text", lambda: "now")


def test_generate_reply_can_skip_persistence_for_auto_command_reply(monkeypatch, tmp_path):
    _use_temp_memory(monkeypatch, tmp_path)
    monkeypatch.setattr(
        ai.client_openai.responses,
        "create",
        lambda **kwargs: SimpleNamespace(output_text="/실행 주사위 1 1 | 나온 값에 4 더해줘"),
    )

    reply = asyncio.run(
        ai.generate_reply(
            "주사위를 굴려서 나온 값에 4 더해줘",
            user_id=123,
            display_name="Alice",
            room_key="room-1",
            persist_command_reply=False,
        )
    )

    data = storage.load_memory()
    assert reply.startswith("/실행 ")
    assert data["123"]["history"] == []
    assert data[ROOMS_KEY]["room-1"]["history"] == []


def test_generate_reply_persists_natural_reply_when_command_persistence_is_disabled(monkeypatch, tmp_path):
    _use_temp_memory(monkeypatch, tmp_path)
    monkeypatch.setattr(
        ai.client_openai.responses,
        "create",
        lambda **kwargs: SimpleNamespace(output_text="결과에 4를 더하면 5야."),
    )

    reply = asyncio.run(
        ai.generate_reply(
            "주사위를 굴려서 나온 값에 4 더해줘",
            user_id=123,
            display_name="Alice",
            room_key="room-1",
            persist_command_reply=False,
        )
    )

    data = storage.load_memory()
    assert reply == "결과에 4를 더하면 5야."
    assert [item["content"] for item in data["123"]["history"]] == [
        "주사위를 굴려서 나온 값에 4 더해줘",
        "결과에 4를 더하면 5야.",
    ]
    assert [item["content"] for item in data[ROOMS_KEY]["room-1"]["history"]] == [
        "주사위를 굴려서 나온 값에 4 더해줘",
        "결과에 4를 더하면 5야.",
    ]


def test_generate_reply_passes_room_reasoning_effort(monkeypatch, tmp_path):
    _use_temp_memory(monkeypatch, tmp_path)
    storage.save_memory({
        ROOMS_KEY: {
            "room-1": {
                "internet_mode": False,
                "group_mode": False,
                "reasoning_effort": "high",
                "history": [],
            }
        }
    })
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(output_text="깊게 생각해봤어.")

    monkeypatch.setattr(ai.client_openai.responses, "create", fake_create)

    asyncio.run(
        ai.generate_reply(
            "조금 복잡한 문제야",
            user_id=123,
            display_name="Alice",
            room_key="room-1",
        )
    )

    assert captured["reasoning"] == {"effort": "high"}


def test_generate_reply_can_skip_keyword_affection_adjustment(monkeypatch, tmp_path):
    _use_temp_memory(monkeypatch, tmp_path)
    storage.save_memory({
        "123456789012345": {
            "name": "Alice",
            "nickname": "Alice",
            "affection": 52,
            "history": [],
        },
    })
    monkeypatch.setattr(
        ai.client_openai.responses,
        "create",
        lambda **kwargs: SimpleNamespace(output_text="나도 고마워."),
    )

    asyncio.run(
        ai.generate_reply(
            "고마워",
            user_id=123456789012345,
            display_name="Alice",
            room_key="room-1",
            apply_affection_adjustment=False,
        )
    )

    data = storage.load_memory()["123456789012345"]
    assert data["affection"] == 52
    assert data["history"][1]["affection_delta"] == 0


def test_generate_silent_auto_command_does_not_persist_hidden_reply(monkeypatch, tmp_path):
    _use_temp_memory(monkeypatch, tmp_path)
    storage.save_memory({
        ROOMS_KEY: {
            "room-1": {
                "group_mode": True,
                "internet_mode": False,
                "reasoning_effort": "low",
                "history": [{
                    "speaker": "상범",
                    "role": "user",
                    "content": "나는 반디를 좋아해.",
                    "user_id": SPECIAL_USER_ID,
                    "nickname": "상범",
                    "affection": 1004,
                }],
            }
        }
    })
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            output_text=f"/뇌추가 {SPECIAL_USER_ID} 애정표현: 2"
        )

    monkeypatch.setattr(ai.client_openai.responses, "create", fake_create)

    reply = asyncio.run(
        ai.generate_silent_auto_command(
            "나는 반디를 좋아해.",
            user_id=SPECIAL_USER_ID,
            display_name="상범",
            room_key="room-1",
            allowed_command_prefixes=("/뇌추가", "/호감도증감"),
        )
    )

    data = storage.load_memory()
    assert reply == f"/뇌추가 {SPECIAL_USER_ID} 애정표현: 2"
    assert "조용한 단체 대화 업데이트 점검" in captured["input"][0]["content"]
    assert data[str(SPECIAL_USER_ID)]["history"] == []
    assert [item["content"] for item in data[ROOMS_KEY]["room-1"]["history"]] == [
        "나는 반디를 좋아해."
    ]


def test_plan_tool_use_returns_structured_command_plan(monkeypatch, tmp_path):
    _use_temp_memory(monkeypatch, tmp_path)
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            output_text=(
                '{"mode":"command","commands":["/투표 새 숙소 투표 | 항목수=2 | 더 화이트 | 힐스토리 | 1주일"],'
                '"response":"","confidence":0.94}'
            )
        )

    monkeypatch.setattr(ai.client_openai.responses, "create", fake_create)

    plan = asyncio.run(
        ai.plan_tool_use(
            "화이트랑 힐스토리로 투표 만들어줘",
            user_id=SPECIAL_USER_ID,
            display_name="상범",
            room_key="room-1",
            special_user=True,
        )
    )

    assert plan is not None
    assert plan.mode == "command"
    assert plan.commands == ("/투표 새 숙소 투표 | 항목수=2 | 더 화이트 | 힐스토리 | 1주일",)
    assert plan.confidence == 0.94
    assert "도구 선택 전용 규칙" in captured["input"][0]["content"]
    assert "반디의 성격" in captured["input"][0]["content"]


def test_plan_tool_use_ignores_low_confidence_chat_plan(monkeypatch, tmp_path):
    _use_temp_memory(monkeypatch, tmp_path)

    monkeypatch.setattr(
        ai.client_openai.responses,
        "create",
        lambda **kwargs: SimpleNamespace(
            output_text='{"mode":"chat","commands":[],"response":"","confidence":0.0}'
        ),
    )

    plan = asyncio.run(
        ai.plan_tool_use(
            "프로필 보여줘",
            user_id=123,
            display_name="Alice",
            room_key="room-1",
            special_user=False,
        )
    )

    assert plan is None


def test_plan_state_updates_returns_allowed_hidden_commands(monkeypatch, tmp_path):
    _use_temp_memory(monkeypatch, tmp_path)
    target_id = 123456789012345
    storage.save_memory({
        str(target_id): {"name": "Alice", "nickname": "개척자", "affection": 48, "history": []},
    })
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            output_text=(
                '{"mode":"command","commands":['
                '"/뇌추가 123456789012345 짧은답변선호: 3",'
                '"/호감도증감 123456789012345 2",'
                '"/뇌추가 123456789012345 작업방식: 2",'
                '"/호감도증감 999999999999999 -5",'
                '"/호감도증감 123456789012345 9",'
                '"/주사위 1 6"],"response":"","confidence":0.88}'
            )
        )

    monkeypatch.setattr(ai.client_openai.responses, "create", fake_create)

    planned = asyncio.run(
        ai.plan_state_updates(
            "짧게 답해주면 좋아.",
            user_id=target_id,
            display_name="Alice",
            room_key="room-1",
        )
    )

    assert planned == (
        "/뇌추가 123456789012345 짧은답변선호: 3",
        "/호감도증감 123456789012345 2",
    )
    assert "대화 상태 업데이트 전용 규칙" in captured["input"][0]["content"]
    assert "현재 호감도: 48" in captured["input"][1]["content"]
    assert "반디가 이미 가진 키워드 점수 딕셔너리" in captured["input"][1]["content"]
    assert "비슷한 의미는 새 키워드로 만들지 말고" in captured["input"][1]["content"]


def test_plan_state_updates_accepts_more_frequent_low_confidence_commands(monkeypatch, tmp_path):
    _use_temp_memory(monkeypatch, tmp_path)
    target_id = 123456789012345
    storage.save_memory({
        str(target_id): {"name": "Alice", "nickname": "개척자", "affection": 48, "history": []},
    })

    monkeypatch.setattr(
        ai.client_openai.responses,
        "create",
        lambda **kwargs: SimpleNamespace(
            output_text=(
                '{"mode":"command","commands":['
                '"/뇌추가 123456789012345 애정표현: 2"'
                '],"response":"","confidence":0.12}'
            )
        ),
    )

    planned = asyncio.run(
        ai.plan_state_updates(
            "반디 사랑해.",
            user_id=target_id,
            display_name="Alice",
            room_key="room-1",
        )
    )

    assert planned == (
        "/뇌추가 123456789012345 애정표현: 2",
    )


def test_plan_state_updates_still_ignores_very_low_confidence_commands(monkeypatch, tmp_path):
    _use_temp_memory(monkeypatch, tmp_path)
    target_id = 123456789012345
    storage.save_memory({
        str(target_id): {"name": "Alice", "nickname": "개척자", "affection": 48, "history": []},
    })

    monkeypatch.setattr(
        ai.client_openai.responses,
        "create",
        lambda **kwargs: SimpleNamespace(
            output_text=(
                '{"mode":"command","commands":['
                '"/뇌추가 123456789012345 애정표현: 2"'
                '],"response":"","confidence":0.05}'
            )
        ),
    )

    planned = asyncio.run(
        ai.plan_state_updates(
            "반디 사랑해.",
            user_id=target_id,
            display_name="Alice",
            room_key="room-1",
        )
    )

    assert planned == ()
