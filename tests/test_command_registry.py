from firefly.command_registry import (
    ADMIN_STATUS_COMMAND,
    BANDI_VOICE_COMMAND,
    ROLE_COMMAND,
    RUNPOD_QUEUE_COMMAND,
    matched_alias,
    registered_special_only_prefixes,
)


def test_registered_special_only_prefixes_include_new_commands():
    prefixes = registered_special_only_prefixes()

    assert "/봇상태" in prefixes
    assert "/역할" in prefixes
    assert "/음성생성" in prefixes
    assert "/음성큐비우기" in prefixes


def test_matched_alias_uses_command_boundary():
    assert matched_alias("/봇상태", ADMIN_STATUS_COMMAND.aliases) == "/봇상태"
    assert matched_alias("/역할 부여 @유저 @운영진", ROLE_COMMAND.aliases) == "/역할"
    assert matched_alias("/음성생성 안녕", BANDI_VOICE_COMMAND.aliases) == "/음성생성"
    assert matched_alias("/음성큐비우기 확인", RUNPOD_QUEUE_COMMAND.aliases) == "/음성큐비우기"
    assert matched_alias("/봇상태보기", ADMIN_STATUS_COMMAND.aliases) is None
