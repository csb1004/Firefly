from firefly import commands_parser
from firefly.config import SUMMARY_DEFAULT_LIMIT


def test_command_arg_returns_text_after_exact_command_prefix():
    assert commands_parser.command_arg("/요약 room 10", "/요약") == "room 10"
    assert commands_parser.command_arg("/요약", "/요약") == ""


def test_parse_summary_args_defaults_from_group_mode_and_supports_korean_scope():
    assert commands_parser.parse_summary_args("/요약", {"group_mode": True}) == ("room", SUMMARY_DEFAULT_LIMIT)
    assert commands_parser.parse_summary_args("/요약 개인 0", {"group_mode": True}) == ("user", 1)
    assert commands_parser.parse_summary_args("/요약 방 999", {"group_mode": False}) == ("room", 80)


def test_new_reasoning_and_brain_commands_are_special_only():
    for command in (
        "/추론",
        "/추론설정 높음",
        "/메모리 파일",
        "/memoryfile",
        "/뇌 123456789012345",
        "/뇌추가 123456789012345 애정표현: 3",
        "/뇌수정 123456789012345 1 애정표현: 8",
        "/뇌삭제 123456789012345 1",
    ):
        assert commands_parser.is_special_only_command(command)
