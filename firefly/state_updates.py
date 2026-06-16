import re
from dataclasses import dataclass

from .config import SPECIAL_USER_ID
from .text_utils import parse_last_int_arg


STATE_UPDATE_COMMAND_PREFIXES = ("/뇌추가", "/호감도증감")
MAX_STATE_UPDATE_COMMANDS = 2
MAX_HIDDEN_AFFECTION_DELTA = 5

_STATE_UPDATE_TARGET_PATTERN = re.compile(
    r"^(/(?:뇌추가|호감도증감))\s+(?:<@!?(\d{1,25})>|@?(\d{1,25}))(?:\s+(.+))?$"
)


@dataclass(frozen=True)
class StateUpdateCommand:
    prefix: str
    target_user_id: int
    remainder: str


def is_state_update_command(command_text: str) -> bool:
    return any(
        command_text == prefix or command_text.startswith(f"{prefix} ")
        for prefix in STATE_UPDATE_COMMAND_PREFIXES
    )


def parse_state_update_command(command_text: str) -> StateUpdateCommand | None:
    match = _STATE_UPDATE_TARGET_PATTERN.match(command_text.strip())
    if not match:
        return None

    target_user_id = int(match.group(2) or match.group(3))
    return StateUpdateCommand(
        prefix=match.group(1),
        target_user_id=target_user_id,
        remainder=(match.group(4) or "").strip(),
    )


def hidden_state_update_allowed(command_text: str, *, user_id: int) -> bool:
    parsed = parse_state_update_command(command_text)
    if parsed is None or parsed.target_user_id != user_id:
        return False

    if parsed.prefix == "/뇌추가":
        return bool(parsed.remainder)

    if parsed.prefix == "/호감도증감":
        if parsed.target_user_id == SPECIAL_USER_ID:
            return False
        delta = parse_last_int_arg(parsed.remainder)
        return delta is not None and abs(delta) <= MAX_HIDDEN_AFFECTION_DELTA

    return False


def filter_hidden_state_update_commands(commands: tuple[str, ...], *, user_id: int) -> tuple[str, ...]:
    allowed = [
        command
        for command in commands
        if hidden_state_update_allowed(command, user_id=user_id)
    ]
    return tuple(allowed[:MAX_STATE_UPDATE_COMMANDS])


def has_hidden_affection_update(commands: tuple[str, ...], *, user_id: int) -> bool:
    return any(
        (parsed := parse_state_update_command(command)) is not None
        and parsed.prefix == "/호감도증감"
        and hidden_state_update_allowed(command, user_id=user_id)
        for command in commands
    )
