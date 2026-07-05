from firefly.state_updates import (
    MAX_STATE_UPDATE_COMMANDS,
    filter_hidden_state_update_commands,
    has_hidden_affection_update,
)


def test_hidden_state_updates_only_allow_current_user_and_bounded_delta():
    commands = (
        "/뇌추가 123456789012345 짧은답변선호: 3",
        "/호감도증감 123456789012345 2",
        "/뇌추가 999999999999999 애정표현: 3",
        "/호감도증감 123456789012345 9",
        "/호감도증감 999999999999999 -5",
    )

    filtered = filter_hidden_state_update_commands(commands, user_id=123456789012345)

    assert filtered == commands[:MAX_STATE_UPDATE_COMMANDS]
    assert has_hidden_affection_update(filtered, user_id=123456789012345)
