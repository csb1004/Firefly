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
            output_text=f"/뇌추가 {SPECIAL_USER_ID} 사용자는 반디에게 좋아해라고 애정을 표현했다."
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
    assert reply == f"/뇌추가 {SPECIAL_USER_ID} 사용자는 반디에게 좋아해라고 애정을 표현했다."
    assert "조용한 단체 대화 업데이트 점검" in captured["input"][0]["content"]
    assert data[str(SPECIAL_USER_ID)]["history"] == []
    assert [item["content"] for item in data[ROOMS_KEY]["room-1"]["history"]] == [
        "나는 반디를 좋아해."
    ]
