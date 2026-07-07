from dataclasses import dataclass


@dataclass(frozen=True)
class TextCommandSpec:
    aliases: tuple[str, ...]
    special_only: bool = False
    summary: str = ""


ADMIN_STATUS_COMMAND = TextCommandSpec(
    aliases=("/봇상태", "/관리상태", "/bot-status"),
    special_only=True,
    summary="Show runtime memory, room, news, and poll status.",
)

ROLE_COMMAND = TextCommandSpec(
    aliases=("/역할", "/role"),
    special_only=True,
    summary="Manage Discord roles, colors, names, assignments, and permissions.",
)

BANDI_VOICE_COMMAND = TextCommandSpec(
    aliases=("/음성생성", "/목소리", "/voice"),
    special_only=True,
    summary="Generate a Bandi voice WAV file from text.",
)


REGISTERED_TEXT_COMMANDS = (
    ADMIN_STATUS_COMMAND,
    ROLE_COMMAND,
    BANDI_VOICE_COMMAND,
)


def registered_special_only_prefixes() -> tuple[str, ...]:
    return tuple(
        alias
        for command in REGISTERED_TEXT_COMMANDS
        if command.special_only
        for alias in command.aliases
    )


def matched_alias(user_text: str, aliases: tuple[str, ...]) -> str | None:
    return next(
        (
            alias
            for alias in aliases
            if user_text == alias or user_text.startswith(f"{alias} ")
        ),
        None,
    )
