from firefly.command_registry import (
    ADMIN_STATUS_COMMAND,
    ROLE_COMMAND,
    VOICE_SEARCH_COMMAND,
    matched_alias,
    registered_special_only_prefixes,
)


def test_registered_special_only_prefixes_include_new_commands():
    prefixes = registered_special_only_prefixes()

    assert "/기록검색" in prefixes
    assert "/봇상태" in prefixes
    assert "/역할" in prefixes


def test_matched_alias_uses_command_boundary():
    assert matched_alias("/기록검색 pizza", VOICE_SEARCH_COMMAND.aliases) == "/기록검색"
    assert matched_alias("/봇상태", ADMIN_STATUS_COMMAND.aliases) == "/봇상태"
    assert matched_alias("/역할 부여 @유저 @운영진", ROLE_COMMAND.aliases) == "/역할"
    assert matched_alias("/기록검색하기", VOICE_SEARCH_COMMAND.aliases) is None
