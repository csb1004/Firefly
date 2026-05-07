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


def clean_mention(message_content: str, bot_user_id: int) -> str:
    return (
        message_content
        .replace(f"<@{bot_user_id}>", "")
        .replace(f"<@!{bot_user_id}>", "")
        .strip()
    )


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
