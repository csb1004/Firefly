from dataclasses import dataclass


@dataclass(frozen=True)
class TextCommandSpec:
    aliases: tuple[str, ...]
    special_only: bool = False
    summary: str = ""


VOICE_SEARCH_COMMAND = TextCommandSpec(
    aliases=("/기록검색", "/녹음검색", "/record-search"),
    special_only=True,
    summary="Search saved voice transcripts with a natural-language question.",
)

ADMIN_STATUS_COMMAND = TextCommandSpec(
    aliases=("/봇상태", "/관리상태", "/bot-status"),
    special_only=True,
    summary="Show runtime memory, room, news, poll, and recording status.",
)


REGISTERED_TEXT_COMMANDS = (
    VOICE_SEARCH_COMMAND,
    ADMIN_STATUS_COMMAND,
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
