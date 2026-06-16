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
    assert commands_parser.summary_recording_filename("/요약 1번") == "1번"
    assert commands_parser.summary_recording_filename("/요약 #1") == "#1"
    assert commands_parser.summary_recording_filename("/요약 voice-20260516.jsonl") == "voice-20260516.jsonl"


def test_parse_summary_args_defaults_from_group_mode_and_supports_korean_scope():
    assert commands_parser.parse_summary_args("/요약", {"group_mode": True}) == ("room", SUMMARY_DEFAULT_LIMIT)
    assert commands_parser.parse_summary_args("/요약 개인 0", {"group_mode": True}) == ("user", 1)
    assert commands_parser.parse_summary_args("/요약 방 999", {"group_mode": False}) == ("room", 80)


def test_normalize_natural_command_is_deferred_to_tool_planner():
    assert commands_parser.normalize_natural_command("칭호를 새별이라고 바꿔줘") is None
    assert commands_parser.normalize_natural_command("1부터 6까지 주사위 굴려줘") is None
    assert commands_parser.normalize_natural_command("최신 소식 받고 싶어", special_user=True) is None


def test_new_reasoning_and_brain_commands_are_special_only():
    for command in (
        "/추론",
        "/추론설정 높음",
        "/메모리 파일",
        "/memoryfile",
        "/뇌 123456789012345",
        "/뇌추가 123456789012345 평가",
        "/뇌수정 123456789012345 1 평가",
        "/뇌삭제 123456789012345 1",
    ):
        assert commands_parser.is_special_only_command(command)
