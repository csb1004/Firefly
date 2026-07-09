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


def _get_int_env(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    raw_value = os.getenv(name, "").strip()
    if raw_value:
        try:
            value = int(raw_value)
        except ValueError as exc:
            raise ValueError(f"{name} must be an integer.") from exc
    else:
        value = default

    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}.")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be at most {maximum}.")
    return value


def _get_float_env(name: str, default: float, *, minimum: float | None = None, maximum: float | None = None) -> float:
    raw_value = os.getenv(name, "").strip()
    if raw_value:
        try:
            value = float(raw_value)
        except ValueError as exc:
            raise ValueError(f"{name} must be a number.") from exc
    else:
        value = default

    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}.")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be at most {maximum}.")
    return value


def _resolve_project_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return BASE_DIR / path


def _resolve_data_dir() -> Path:
    env_value = os.getenv("DATA_DIR", "").strip()
    if env_value:
        return _resolve_project_path(env_value)

    default_data_dir = Path("/data")
    if default_data_dir.is_absolute() and default_data_dir.exists():
        return default_data_dir

    return BASE_DIR / "data"


def _resolve_memory_file(data_dir: Path) -> Path:
    env_value = os.getenv("MEMORY_FILE", "").strip()
    if env_value:
        return _resolve_project_path(env_value)
    return data_dir / "memory.json"


DISCORD_BOT_TOKEN = _get_required_env("DISCORD_BOT_TOKEN")
OPENAI_API_KEY = _get_required_env("OPENAI_API_KEY")

DEFAULT_PROMPT_FILE = _resolve_project_path(os.getenv("DEFAULT_PROMPT_FILE", "prompt.txt"))
SPECIAL_PROMPT_FILE = _resolve_project_path(os.getenv("SPECIAL_PROMPT_FILE", "prompt_special.txt"))
COMMAND_GUIDE_FILE = _resolve_project_path(os.getenv("COMMAND_GUIDE_FILE", "prompt_commands_general.txt"))
SPECIAL_COMMAND_GUIDE_FILE = _resolve_project_path(
    os.getenv("SPECIAL_COMMAND_GUIDE_FILE", "prompt_commands_special.txt")
)
TOOL_PLANNER_PROMPT_FILE = _resolve_project_path(os.getenv("TOOL_PLANNER_PROMPT_FILE", "prompt_tool_planner.txt"))
STATE_UPDATER_PROMPT_FILE = _resolve_project_path(
    os.getenv("STATE_UPDATER_PROMPT_FILE", "prompt_state_updater.txt")
)

DATA_DIR = _resolve_data_dir()
MEMORY_FILE = _resolve_memory_file(DATA_DIR)

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
DAILY_NEWS_KEY = "__daily_news__"

NEWS_PROMPT_FILE = _resolve_project_path(os.getenv("NEWS_PROMPT_FILE", "prompt_news.txt"))
NEWS_DEFAULT_HOUR = 9
NEWS_DEFAULT_MINUTE = 0
NEWS_DEFAULT_TOPICS = ["인공지능", "프로그래밍"]

DEFAULT_MODEL = "gpt-5.3-codex"
TOOL_PLANNER_MODEL = os.getenv("TOOL_PLANNER_MODEL", DEFAULT_MODEL)
STATE_UPDATER_MODEL = os.getenv("STATE_UPDATER_MODEL", DEFAULT_MODEL)
BANDI_VOICE_PREPROCESS_MODEL = os.getenv("BANDI_VOICE_PREPROCESS_MODEL", DEFAULT_MODEL)
WEB_SEARCH_MODEL = "gpt-5.4"

BANDI_TTS_URL = os.getenv("BANDI_TTS_URL", "").strip()
BANDI_TTS_API_KEY = os.getenv("BANDI_TTS_API_KEY", "").strip()
BANDI_TTS_TIMEOUT_SECONDS = _get_float_env("BANDI_TTS_TIMEOUT_SECONDS", 300.0, minimum=1.0, maximum=3600.0)
RUNPOD_TTS_TIMEOUT_SECONDS = _get_float_env("RUNPOD_TTS_TIMEOUT_SECONDS", 900.0, minimum=1.0, maximum=3600.0)
BANDI_TTS_MAX_CHARS = _get_int_env("BANDI_TTS_MAX_CHARS", 500, minimum=1, maximum=2000)
BANDI_TTS_MIN_DURATION_SECONDS = _get_float_env("BANDI_TTS_MIN_DURATION_SECONDS", 0.0, minimum=0.0, maximum=60.0)
BANDI_TTS_RETRY_ATTEMPTS = _get_int_env("BANDI_TTS_RETRY_ATTEMPTS", 1, minimum=1, maximum=10)
RUNPOD_ENDPOINT_ID = os.getenv("RUNPOD_ENDPOINT_ID", "").strip()
RUNPOD_API_KEY = os.getenv("RUNPOD_API_KEY", "").strip()
