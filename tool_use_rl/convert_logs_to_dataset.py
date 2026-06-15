import argparse
import json
from pathlib import Path
from typing import Any

try:
    from .tool_usage_logger import DEFAULT_LOG_PATH
except ImportError:
    from tool_usage_logger import DEFAULT_LOG_PATH


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "tool_usage_dataset.jsonl"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def convert_logs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dataset = []
    for index, row in enumerate(rows):
        selected = row.get("selected_tools") or []
        if not selected:
            continue
        dataset.append({
            "id": f"log-{index}",
            "user_message": row.get("user_message", ""),
            "actions": selected,
            "difficulty": "real-usage",
            "is_ambiguous": False,
            "context": {
                "timestamp": row.get("timestamp"),
                "assistant_response": row.get("assistant_response", ""),
            },
            "reason": "Converted from Discord tool usage log.",
            "split": "train",
            "reward": row.get("reward"),
            "feedback": row.get("feedback"),
        })
    return dataset


def _write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert real tool usage logs to training data.")
    parser.add_argument("--input", type=Path, default=DEFAULT_LOG_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    rows = convert_logs(_read_jsonl(args.input))
    _write_jsonl(rows, args.output)
    print(f"Wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
