import pytest

from firefly.utility_commands import (
    CommandUsageError,
    format_dice_result,
    format_team_split_result,
    parse_command_adapter_args,
    parse_dice_args,
    parse_team_split_args,
    roll_dice,
    split_members_into_teams,
)


class FixedRng:
    def randint(self, start, end):
        return end

    def shuffle(self, members):
        members.reverse()


def test_parse_dice_args_supports_one_or_two_numbers():
    assert parse_dice_args("6").start == 1
    assert parse_dice_args("6").end == 6
    assert parse_dice_args("1 20").start == 1
    assert parse_dice_args("1 20").end == 20


def test_roll_dice_formats_result():
    result = roll_dice(parse_dice_args("1 6"), rng=FixedRng())

    assert result.value == 6
    assert format_dice_result(result) == "주사위 결과: **6** (`1`~`6`)"


def test_parse_dice_args_rejects_reversed_range():
    with pytest.raises(CommandUsageError):
        parse_dice_args("10 1")


def test_parse_team_split_args_supports_team_count_and_commas():
    request = parse_team_split_args("팀수=2 | 철수, 영희, 민수, 수진")

    assert request.team_count == 2
    assert request.members == ("철수", "영희", "민수", "수진")


def test_parse_team_split_args_supports_members_per_team():
    request = parse_team_split_args("팀당=2 | 철수 | 영희 | 민수 | 수진 | 지훈")

    assert request.team_count == 3
    assert request.members == ("철수", "영희", "민수", "수진", "지훈")


def test_split_members_into_balanced_teams():
    request = parse_team_split_args("팀수=2 | 철수, 영희, 민수, 수진")
    teams = split_members_into_teams(request, rng=FixedRng())

    assert teams == [["수진", "영희"], ["민수", "철수"]]
    assert "총 4명, 2팀" in format_team_split_result(request, teams)


def test_parse_command_adapter_args_supports_single_separator():
    request = parse_command_adapter_args("주사위 1 6 | 나온 숫자에 4 더해줘")

    assert request.command_texts == ("/주사위 1 6",)
    assert request.prompt == "나온 숫자에 4 더해줘"


def test_parse_command_adapter_args_supports_double_separator_for_pipe_commands():
    request = parse_command_adapter_args(
        "/팀나누기 팀수=2 | 철수, 영희, 민수, 수진 || 첫 번째 팀만 알려줘"
    )

    assert request.command_texts == ("/팀나누기 팀수=2 | 철수, 영희, 민수, 수진",)
    assert request.prompt == "첫 번째 팀만 알려줘"


def test_parse_command_adapter_args_supports_poll_command_with_followup_prompt():
    request = parse_command_adapter_args(
        "/투표 반디랑 갈 데이트 장소 | 항목수=4 | 조용한 북카페 | "
        "한적한 공원 산책길 | 작은 수족관 | 야경 보이는 강변 | 10분 "
        "|| 고른 이유도 같이 알려줘"
    )

    assert request.command_texts == (
        (
            "/투표 반디랑 갈 데이트 장소 | 항목수=4 | 조용한 북카페 | "
            "한적한 공원 산책길 | 작은 수족관 | 야경 보이는 강변 | 10분"
        ),
    )
    assert request.prompt == "고른 이유도 같이 알려줘"


def test_parse_command_adapter_args_supports_multiple_commands():
    request = parse_command_adapter_args("주사위 1 6 && 프로필 | 결과를 같이 설명해줘")

    assert request.command_texts == ("/주사위 1 6", "/프로필")
    assert request.prompt == "결과를 같이 설명해줘"


def test_parse_command_adapter_args_supports_newline_separated_commands():
    request = parse_command_adapter_args("dice 1 1\nprofile @user | combine the results")

    assert request.command_texts == ("/dice 1 1", "/profile @user")
    assert request.prompt == "combine the results"


def test_parse_command_adapter_args_rejects_too_many_commands():
    with pytest.raises(CommandUsageError):
        parse_command_adapter_args("a && b && c && d && e && f | summarize")


def test_parse_command_adapter_args_supports_prompt_only_when_allowed():
    request = parse_command_adapter_args("최신 AI 소식 알려줘", allow_prompt_only=True)

    assert request.command_texts == ()
    assert request.prompt == "최신 AI 소식 알려줘"
