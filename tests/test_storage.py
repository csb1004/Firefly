from types import SimpleNamespace

import pytest

from firefly import storage
from firefly.config import DEFAULT_AFFECTION, MAX_HISTORY, MAX_ROOM_HISTORY, ROOMS_KEY


@pytest.fixture
def memory_file(tmp_path, monkeypatch):
    path = tmp_path / "memory.json"
    monkeypatch.setattr(storage, "MEMORY_FILE", path)
    return path


def test_load_memory_missing_and_invalid_file_initialize_safely(memory_file):
    assert storage.load_memory() == {}

    memory_file.write_text("{not valid json", encoding="utf-8")

    assert storage.load_memory() == {}


def test_save_memory_writes_json_atomically(memory_file):
    storage.save_memory({"123": {"name": "User"}})

    assert storage.load_memory() == {"123": {"name": "User"}}
    assert not memory_file.with_name("memory.json.tmp").exists()


def test_get_user_data_creates_and_normalizes_defaults(memory_file):
    user_data = storage.get_user_data(123, "Alice")

    assert user_data["name"] == "Alice"
    assert user_data["affection"] == DEFAULT_AFFECTION
    assert user_data["last_seen"] is None
    assert user_data["history"] == []

    data = storage.load_memory()
    data["123"].pop("last_seen")
    data["123"].pop("history")
    storage.save_memory(data)

    normalized = storage.get_user_data(123, "Alice Updated")

    assert normalized["name"] == "Alice Updated"
    assert normalized["last_seen"] is None
    assert normalized["history"] == []


def test_add_history_trims_to_configured_limit():
    user_data = {"history": []}

    for index in range(MAX_HISTORY + 5):
        storage.add_history(user_data, "user", f"message-{index}")

    assert len(user_data["history"]) == MAX_HISTORY
    assert user_data["history"][0]["content"] == "message-5"


def test_room_data_defaults_and_history_trimming(memory_file):
    room_data = storage.get_room_data("guild:channel")

    assert room_data == {"internet_mode": False, "group_mode": False, "history": []}

    for index in range(MAX_ROOM_HISTORY + 3):
        storage.add_room_history(room_data, "Alice", "user", f"room-message-{index}")

    assert len(room_data["history"]) == MAX_ROOM_HISTORY
    assert room_data["history"][0]["content"] == "room-message-3"


def test_record_room_user_message_persists_user_and_room_history(memory_file):
    author = SimpleNamespace(id=321, name="alice", display_name="Alice")
    channel = SimpleNamespace(id=222)
    guild = SimpleNamespace(id=111)
    message = SimpleNamespace(
        author=author,
        channel=channel,
        guild=guild,
        content="hello",
        mentions=[],
        channel_mentions=[],
        role_mentions=[],
    )
    room_key = storage.get_room_key(message)
    room_data = storage.get_room_data(room_key)

    assert storage.record_room_user_message(message, room_key, room_data)

    data = storage.load_memory()
    assert data["321"]["name"] == "Alice"
    assert data[ROOMS_KEY][room_key]["history"][-1]["content"] == "hello"
    assert data[ROOMS_KEY][room_key]["history"][-1]["user_id"] == 321

