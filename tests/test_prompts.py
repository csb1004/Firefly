from firefly import prompts


def test_build_model_history_keeps_recent_chat_messages_and_skips_commands(monkeypatch):
    monkeypatch.setattr(prompts, "MAX_MODEL_HISTORY", 3)
    history = [
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "/help"},
        {"role": "system", "content": "ignore"},
        {"role": "user", "content": "new"},
    ]

    assert prompts.build_model_history(history) == [
        {"role": "user", "content": "new"},
    ]


def test_build_room_model_history_adds_user_metadata_and_skips_commands(monkeypatch):
    monkeypatch.setattr(prompts, "MAX_ROOM_MODEL_HISTORY", 4)
    room_history = [
        {"role": "user", "speaker": "Alice", "content": "hello", "nickname": "Al", "affection": 60},
        {"role": "assistant", "content": "hi"},
        {"role": "user", "speaker": "Bob", "content": "/help"},
        {"role": "assistant", "content": "still here"},
    ]

    model_history = prompts.build_room_model_history(room_history)

    assert model_history[0]["role"] == "user"
    assert "Alice" in model_history[0]["content"]
    assert "Al" in model_history[0]["content"]
    assert "60" in model_history[0]["content"]
    assert model_history[0]["content"].endswith("hello")
    assert model_history[1:] == [
        {"role": "assistant", "content": "hi"},
        {"role": "assistant", "content": "still here"},
    ]


def test_build_group_context_prompt_includes_current_user_and_recent_participants():
    prompt = prompts.build_group_context_prompt(
        display_name="Current",
        user_id=3,
        user_data={"nickname": "Cur", "affection": 70},
        room_data={
            "history": [
                {"role": "user", "user_id": 1, "speaker": "Alice", "nickname": "Al", "affection": 60},
                {"role": "assistant", "speaker": "Bot", "content": "hello"},
                {"role": "user", "user_id": 2, "speaker": "Bob", "nickname": "B", "affection": 40},
            ]
        },
    )

    assert "Current" in prompt
    assert "Cur" in prompt
    assert "70" in prompt
    assert "Alice" in prompt
    assert "Bob" in prompt


def test_build_system_prompt_uses_base_prompt_user_state_and_time(monkeypatch):
    monkeypatch.setattr(prompts, "get_base_prompt", lambda user_id: f"base prompt for {user_id}")
    monkeypatch.setattr(prompts, "get_current_time_text", lambda: "2026-05-16 12:00:00")

    prompt = prompts.build_system_prompt(
        123,
        {"name": "Alice", "nickname": "Al", "affection": 50, "last_seen": "yesterday"},
    )

    assert "base prompt for 123" in prompt
    assert "Alice" in prompt
    assert "Al" in prompt
    assert "50" in prompt
    assert "2026-05-16 12:00:00" in prompt
    assert "yesterday" in prompt

