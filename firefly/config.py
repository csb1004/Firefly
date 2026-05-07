import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def _get_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name}가 .env에 없습니다.")
    return value


def _resolve_project_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return BASE_DIR / path


DISCORD_BOT_TOKEN = _get_required_env("DISCORD_BOT_TOKEN")
OPENAI_API_KEY = _get_required_env("OPENAI_API_KEY")

DEFAULT_PROMPT_FILE = _resolve_project_path(os.getenv("DEFAULT_PROMPT_FILE", "prompt.txt"))
SPECIAL_PROMPT_FILE = _resolve_project_path(os.getenv("SPECIAL_PROMPT_FILE", "prompt_special.txt"))

_memory_path = Path(os.getenv("MEMORY_FILE", "/data/memory.json"))
if not _memory_path.is_absolute():
    MEMORY_FILE = BASE_DIR / _memory_path
elif _memory_path.parent.exists():
    MEMORY_FILE = _memory_path
else:
    MEMORY_FILE = BASE_DIR / "memory.json"

SPECIAL_USER_ID = 393724092022390784
SPECIAL_USER_NAME = "상범"
SPECIAL_USER_NICKNAME = "상범"

BOT_DISPLAY_NAME = "반디"
COMMAND_PREFIX = "/"

DEFAULT_AFFECTION = 50

MAX_HISTORY = 40
MAX_MODEL_HISTORY = 12
ROOMS_KEY = "__rooms__"
MAX_ROOM_HISTORY = 80
MAX_ROOM_MODEL_HISTORY = 12
SUMMARY_DEFAULT_LIMIT = 30

POLLS_KEY = "__polls__"

DEFAULT_MODEL = "gpt-5.3-codex"
WEB_SEARCH_MODEL = "gpt-5.4"
