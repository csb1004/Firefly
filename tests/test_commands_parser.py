from firefly import commands_parser
from firefly.config import SUMMARY_DEFAULT_LIMIT


def test_command_arg_returns_text_after_exact_command_prefix():
    assert commands_parser.command_arg("/요약 room 10", "/요약") == "room 10"
    assert commands_parser.command_arg("/요약", "/요약") == ""


def test_summary_recording_filename_only_accepts_non_scope_first_arg():
    assert commands_parser.summary_recording_filename("/요약") is None
    assert commands_parser.summary_recording_filename("/요약 room 10") is None
    assert commands_parser.summary_recording_filename("/요약 방 10") is None
    assert commands_parser.summary_recording_filename("/요약 10") is None
    assert commands_parser.summary_recording_filename("/요약 voice-20260516.jsonl") == "voice-20260516.jsonl"


def test_parse_summary_args_defaults_from_group_mode_and_supports_korean_scope():
    assert commands_parser.parse_summary_args("/요약", {"group_mode": True}) == ("room", SUMMARY_DEFAULT_LIMIT)
    assert commands_parser.parse_summary_args("/요약 개인 0", {"group_mode": True}) == ("user", 1)
    assert commands_parser.parse_summary_args("/요약 방 999", {"group_mode": False}) == ("room", 80)
