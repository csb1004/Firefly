import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import COMMAND_PREFIX, SPECIAL_USER_ID, SPECIAL_PROMPT_FILE, DEFAULT_PROMPT_FILE


def get_current_time_text() -> str:
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    return now.strftime("%Y-%m-%d %H:%M:%S")


def normalize_text(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[^\w가-힣ㄱ-ㅎㅏ-ㅣ]", "", text)
    return text


def load_text_file(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"{path} 파일을 찾을 수 없어.")
    return path.read_text(encoding="utf-8").strip()


def get_base_prompt(user_id: int) -> str:
    if user_id == SPECIAL_USER_ID:
        return load_text_file(SPECIAL_PROMPT_FILE)
    return load_text_file(DEFAULT_PROMPT_FILE)


def _compact_discord_spacing(text: str) -> str:
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    return text.strip()


def clean_mention(message_content: str, bot_user_id: int) -> str:
    text = re.sub(rf"<@!?{re.escape(str(bot_user_id))}>", "", message_content)
    return _compact_discord_spacing(text)


def _mention_display_name(item: object, fallback: str) -> str:
    return str(
        getattr(
            item,
            "display_name",
            getattr(item, "name", fallback),
        )
    )


def clean_discord_content(
    message: object,
    bot_user_id: int | None = None,
    remove_bot_mention: bool = False,
) -> str:
    text = str(getattr(message, "content", ""))

    users = {
        str(getattr(user, "id")): _mention_display_name(user, str(getattr(user, "id", "")))
        for user in getattr(message, "mentions", [])
        if getattr(user, "id", None) is not None
    }
    channels = {
        str(getattr(channel, "id")): _mention_display_name(channel, str(getattr(channel, "id", "")))
        for channel in getattr(message, "channel_mentions", [])
        if getattr(channel, "id", None) is not None
    }
    roles = {
        str(getattr(role, "id")): _mention_display_name(role, str(getattr(role, "id", "")))
        for role in getattr(message, "role_mentions", [])
        if getattr(role, "id", None) is not None
    }

    bot_id = str(bot_user_id) if bot_user_id is not None else None

    def replace_user_mention(match: re.Match) -> str:
        user_id = match.group(1)
        if remove_bot_mention and bot_id == user_id:
            return ""
        return f"@{users.get(user_id, user_id)}"

    def replace_channel_mention(match: re.Match) -> str:
        channel_id = match.group(1)
        return f"#{channels.get(channel_id, channel_id)}"

    def replace_role_mention(match: re.Match) -> str:
        role_id = match.group(1)
        return f"@{roles.get(role_id, role_id)}"

    text = re.sub(r"<@!?(\d+)>", replace_user_mention, text)
    text = re.sub(r"<#(\d+)>", replace_channel_mention, text)
    text = re.sub(r"<@&(\d+)>", replace_role_mention, text)
    return _compact_discord_spacing(text)


def is_command_text(text: str) -> bool:
    return text.strip().startswith(COMMAND_PREFIX)


def parse_last_int_arg(text: str) -> int | None:
    try:
        return int(text.split()[-1])
    except (IndexError, ValueError):
        return None


def clamp_text(text: str, max_length: int, suffix: str = "...") -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix
