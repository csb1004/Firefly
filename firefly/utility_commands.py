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
    team_sizes: tuple[int, ...] | None = None


@dataclass(frozen=True)
class CommandAdapterRequest:
    command_texts: tuple[str, ...]
    prompt: str


TEAM_COUNT_KEYS = {"팀수", "팀", "조", "조수", "teams", "team_count"}
TEAM_SIZE_KEYS = {"팀당", "팀원", "인원", "size", "team_size", "members_per_team"}
TEAM_EXPLICIT_SIZE_KEYS = {
    "팀별",
    "팀별인원",
    "팀별인원수",
    "팀구성",
    "구성",
    "sizes",
    "team_sizes",
}
MAX_DICE_ABS_VALUE = 1_000_000_000
MAX_TEAM_MEMBERS = 100
MAX_ADAPTER_COMMANDS = 5


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


def _parse_team_sizes(value: str) -> tuple[int, ...]:
    parts = [part for part in re.split(r"[,/+:;]+", value) if part.strip()]
    if len(parts) < 2:
        raise CommandUsageError("팀별 인원은 2개 이상 적어줘. 예: `팀별=3,6`")

    team_sizes = tuple(
        _parse_positive_int(part.strip().removesuffix("명"), "팀별 인원")
        for part in parts
    )
    return team_sizes


def _normalize_explicit_size_tokens(head: str) -> str:
    explicit_size_keys = "|".join(re.escape(key) for key in TEAM_EXPLICIT_SIZE_KEYS)
    return re.sub(
        rf"(^|\s)({explicit_size_keys})\s*=\s*([0-9명\s,/:;+]+)",
        lambda match: (
            f"{match.group(1)}{match.group(2)}={''.join(match.group(3).split())}"
        ),
        head,
    )


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
    head = _normalize_explicit_size_tokens(pipe_parts[0]) if pipe_parts else ""
    member_segments = pipe_parts[1:]
    mode = None
    value = None
    team_sizes = None
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
                    raise CommandUsageError("`팀수`, `팀당`, `팀별`은 하나만 써줘.")
                mode = "teams"
                value = _parse_positive_int(raw_value, "팀수")
            elif key in TEAM_SIZE_KEYS:
                if mode is not None and mode != "size":
                    raise CommandUsageError("`팀수`, `팀당`, `팀별`은 하나만 써줘.")
                mode = "size"
                value = _parse_positive_int(raw_value, "팀당 인원")
            elif key in TEAM_EXPLICIT_SIZE_KEYS:
                if mode is not None and mode != "explicit_sizes":
                    raise CommandUsageError("`팀수`, `팀당`, `팀별`은 하나만 써줘.")
                mode = "explicit_sizes"
                team_sizes = _parse_team_sizes(raw_value)
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
    if mode is None:
        raise CommandUsageError("팀 수나 팀당 인원을 알려줘. 예: `팀수=2`, `팀당=3`, `팀별=3,6`")

    if mode == "explicit_sizes":
        assert team_sizes is not None
        team_count = len(team_sizes)
        assigned_count = sum(team_sizes)
        if assigned_count != len(members):
            raise CommandUsageError(
                f"팀별 인원 합계는 참가자 수와 같아야 해. 지금은 참가자 {len(members)}명 중 {assigned_count}명으로 적었어."
            )
    elif mode == "size":
        assert value is not None
        team_count = math.ceil(len(members) / value)
    else:
        assert value is not None
        team_count = value

    if team_count < 2:
        raise CommandUsageError("팀은 최소 2팀 이상이어야 해.")
    if team_count > len(members):
        raise CommandUsageError("팀 수는 참가자 수보다 많을 수 없어.")

    return TeamSplitRequest(members=tuple(members), team_count=team_count, team_sizes=team_sizes)


def split_members_into_teams(
    request: TeamSplitRequest,
    rng: random.Random | None = None,
) -> list[list[str]]:
    rng = rng or random.SystemRandom()
    members = list(request.members)
    rng.shuffle(members)

    if request.team_sizes is not None:
        teams = []
        start = 0
        for team_size in request.team_sizes:
            end = start + team_size
            teams.append(members[start:end])
            start = end
        return teams

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


def _normalize_adapter_command(command_text: str) -> str:
    command_text = command_text.strip()
    if not command_text:
        raise CommandUsageError("실행할 명령어 이름이 비어 있어.")
    if not command_text.startswith("/"):
        command_text = f"/{command_text}"
    if command_text == "/":
        raise CommandUsageError("실행할 명령어 이름이 비어 있어.")
    return command_text


def _split_adapter_commands(command_block: str) -> tuple[str, ...]:
    raw_commands = [
        part.strip()
        for part in re.split(r"\s*(?:&&|\n+)\s*", command_block.strip())
        if part.strip()
    ]
    if not raw_commands:
        raise CommandUsageError("먼저 실행할 명령어를 적어줘.")
    if len(raw_commands) > MAX_ADAPTER_COMMANDS:
        raise CommandUsageError(f"`/실행`에서는 명령어를 한 번에 최대 {MAX_ADAPTER_COMMANDS}개까지 실행할 수 있어.")
    return tuple(_normalize_adapter_command(command) for command in raw_commands)


def parse_command_adapter_args(
    raw_text: str,
    *,
    allow_prompt_only: bool = False,
) -> CommandAdapterRequest:
    text = raw_text.strip()
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()

    if "||" in text:
        command_text, separator, prompt = text.partition("||")
    else:
        command_text, separator, prompt = text.partition("|")
    if not separator:
        if allow_prompt_only and text:
            return CommandAdapterRequest(command_texts=(), prompt=text)
        raise CommandUsageError(
            "사용법: `/실행 주사위 1 6 | 주사위를 굴려서 나온 숫자에 4 더해줘`"
        )

    command_text = command_text.strip()
    prompt = prompt.strip()
    if not command_text and not allow_prompt_only:
        raise CommandUsageError("먼저 실행할 명령어를 적어줘.")
    if not prompt:
        raise CommandUsageError("명령어 결과로 이어서 답할 프롬프트를 적어줘.")

    command_texts = _split_adapter_commands(command_text) if command_text else ()
    return CommandAdapterRequest(command_texts=command_texts, prompt=prompt)
