import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_PATH = PROJECT_ROOT / "logs" / "tool_usage.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_tool_usage(
    *,
    user_message: str,
    selected_tools: list[str],
    tool_results: list[str] | None = None,
    assistant_response: str = "",
    feedback: Any = None,
    reward: float | None = None,
    log_path: Path | None = None,
) -> None:
    if os.getenv("PYTEST_CURRENT_TEST"):
        return
    if os.getenv("FIREFLY_TOOL_USAGE_LOGGING", "1").lower() in {"0", "false", "off"}:
        return

    path = log_path or DEFAULT_LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp": _now_iso(),
        "user_message": user_message,
        "selected_tools": selected_tools,
        "tool_results": tool_results or [],
        "assistant_response": assistant_response,
        "feedback": feedback,
        "reward": reward,
    }
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(row, ensure_ascii=False) + "\n")
