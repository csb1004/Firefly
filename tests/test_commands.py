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
    assert commands._summary_recording_filename("/요약 voice-20260516.jsonl") == "voice-20260516.jsonl"

