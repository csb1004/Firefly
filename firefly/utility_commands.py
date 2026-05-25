import math
import random
import re
from dataclasses import dataclass


class CommandUsageError(ValueError):
    pass


@dataclass(frozen=True)
class DiceRequest:
    start: int
    end: int


@dataclass(frozen=True)
class DiceResult:
    start: int
    end: int
    value: int


@dataclass(frozen=True)
class TeamSplitRequest:
    members: tuple[str, ...]
    team_count: int


@dataclass(frozen=True)
class CommandAdapterRequest:
    command_text: str
    prompt: str


TEAM_COUNT_KEYS = {"팀수", "팀", "조", "조수", "teams", "team_count"}
TEAM_SIZE_KEYS = {"팀당", "팀원", "인원", "size", "team_size", "members_per_team"}
MAX_DICE_ABS_VALUE = 1_000_000_000
MAX_TEAM_MEMBERS = 100


def parse_dice_args(raw_text: str) -> DiceRequest:
    numbers = [int(value) for value in re.findall(r"-?\d+", raw_text)]
    if not numbers:
        raise CommandUsageError("사용법: `/주사위 1 6` 또는 `/주사위 6`")

    if len(numbers) == 1:
        start, end = 1, numbers[0]
    else:
        start, end = numbers[0], numbers[1]

    if start > end:
        raise CommandUsageError("주사위 시작 숫자는 끝 숫자보다 작거나 같아야 해.")
    if abs(start) > MAX_DICE_ABS_VALUE or abs(end) > MAX_DICE_ABS_VALUE:
        raise CommandUsageError("주사위 범위는 -1,000,000,000부터 1,000,000,000까지만 가능해.")

    return DiceRequest(start=start, end=end)


def roll_dice(request: DiceRequest, rng: random.Random | None = None) -> DiceResult:
    rng = rng or random.SystemRandom()
    return DiceResult(
        start=request.start,
        end=request.end,
        value=rng.randint(request.start, request.end),
    )


def format_dice_result(result: DiceResult) -> str:
    return f"주사위 결과: **{result.value}** (`{result.start}`~`{result.end}`)"


def _parse_positive_int(value: str, label: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise CommandUsageError(f"{label}은 숫자로 적어줘.") from exc
    if parsed <= 0:
        raise CommandUsageError(f"{label}은 1보다 커야 해.")
    return parsed


def _split_member_segments(segments: list[str]) -> list[str]:
    members = []
    for segment in segments:
        if not segment.strip():
            continue
        if "," in segment:
            parts = segment.split(",")
        else:
            parts = re.split(r"\s+", segment)
        members.extend(part.strip() for part in parts if part.strip())
    return members


def parse_team_split_args(raw_text: str) -> TeamSplitRequest:
    text = raw_text.strip()
    if not text:
        raise CommandUsageError(
            "사용법: `/팀나누기 팀수=2 | 철수, 영희, 민수, 수진`"
        )

    pipe_parts = [part.strip() for part in text.split("|") if part.strip()]
    head = pipe_parts[0] if pipe_parts else ""
    member_segments = pipe_parts[1:]
    mode = None
    value = None
    residual_tokens = []

    for token in head.split():
        normalized = token.strip()
        if not normalized:
            continue

        if "=" in normalized:
            key, raw_value = normalized.split("=", 1)
            key = key.strip().lower()
            raw_value = raw_value.strip()
            if key in TEAM_COUNT_KEYS:
                if mode is not None and mode != "teams":
                    raise CommandUsageError("`팀수`와 `팀당`은 둘 중 하나만 써줘.")
                mode = "teams"
                value = _parse_positive_int(raw_value, "팀수")
            elif key in TEAM_SIZE_KEYS:
                if mode is not None and mode != "size":
                    raise CommandUsageError("`팀수`와 `팀당`은 둘 중 하나만 써줘.")
                mode = "size"
                value = _parse_positive_int(raw_value, "팀당 인원")
            else:
                residual_tokens.append(normalized)
        elif mode is None and value is None and normalized.isdigit():
            mode = "teams"
            value = _parse_positive_int(normalized, "팀수")
        else:
            residual_tokens.append(normalized)

    if residual_tokens:
        member_segments.insert(0, " ".join(residual_tokens))

    members = _split_member_segments(member_segments)
    if len(members) < 2:
        raise CommandUsageError("팀을 나누려면 참가자가 최소 2명 필요해.")
    if len(members) > MAX_TEAM_MEMBERS:
        raise CommandUsageError(f"참가자는 한 번에 최대 {MAX_TEAM_MEMBERS}명까지만 나눌 수 있어.")
    if mode is None or value is None:
        raise CommandUsageError("팀 수나 팀당 인원을 알려줘. 예: `팀수=2` 또는 `팀당=3`")

    if mode == "size":
        team_count = math.ceil(len(members) / value)
    else:
        team_count = value

    if team_count < 2:
        raise CommandUsageError("팀은 최소 2팀 이상이어야 해.")
    if team_count > len(members):
        raise CommandUsageError("팀 수는 참가자 수보다 많을 수 없어.")

    return TeamSplitRequest(members=tuple(members), team_count=team_count)


def split_members_into_teams(
    request: TeamSplitRequest,
    rng: random.Random | None = None,
) -> list[list[str]]:
    rng = rng or random.SystemRandom()
    members = list(request.members)
    rng.shuffle(members)
    teams = [[] for _ in range(request.team_count)]

    for index, member in enumerate(members):
        teams[index % request.team_count].append(member)

    return teams


def format_team_split_result(request: TeamSplitRequest, teams: list[list[str]]) -> str:
    lines = [
        f"팀 나누기 결과: 총 {len(request.members)}명, {request.team_count}팀",
    ]
    for index, team in enumerate(teams, start=1):
        lines.append(f"{index}팀: {', '.join(team)}")
    return "\n".join(lines)


def parse_command_adapter_args(raw_text: str) -> CommandAdapterRequest:
    text = raw_text.strip()
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()

    if "||" in text:
        command_text, separator, prompt = text.partition("||")
    else:
        command_text, separator, prompt = text.partition("|")
    if not separator:
        raise CommandUsageError(
            "사용법: `/실행 주사위 1 6 | 주사위를 굴려서 나온 숫자에 4 더해줘`"
        )

    command_text = command_text.strip()
    prompt = prompt.strip()
    if not command_text:
        raise CommandUsageError("먼저 실행할 명령어를 적어줘.")
    if not prompt:
        raise CommandUsageError("명령어 결과로 이어서 답할 프롬프트를 적어줘.")

    if not command_text.startswith("/"):
        command_text = f"/{command_text}"

    if command_text == "/":
        raise CommandUsageError("실행할 명령어 이름이 비어 있어.")

    return CommandAdapterRequest(command_text=command_text, prompt=prompt)
