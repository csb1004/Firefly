import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_DATASET = ROOT / "synthetic_tool_dataset.jsonl"
DEFAULT_MODEL = ROOT / "tool_selector_model.json"


def tokenize(text: str) -> list[str]:
    return re.findall(r"[0-9A-Za-z가-힣_/-]+", text.casefold())


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def train(rows: list[dict[str, Any]]) -> dict[str, Any]:
    train_rows = [row for row in rows if row.get("split", "train") == "train"]
    if not train_rows:
        train_rows = rows

    tool_counts = Counter(action for row in train_rows for action in row.get("actions", []))
    token_counts: dict[str, Counter[str]] = defaultdict(Counter)
    document_counts = Counter()

    for row in train_rows:
        tokens = set(tokenize(row.get("user_message", "")))
        for token in tokens:
            document_counts[token] += 1
        for action in row.get("actions", []):
            for token in tokens:
                token_counts[token][action] += 1

    row_count = max(1, len(train_rows))
    token_weights = {}
    for token, counts in token_counts.items():
        idf = math.log((row_count + 1) / (document_counts[token] + 1)) + 1.0
        token_weights[token] = {
            tool: round(count * idf, 6)
            for tool, count in counts.items()
        }

    return {
        "version": 1,
        "model_type": "standard-library behavior-cloning ranker",
        "row_count": len(train_rows),
        "tools": sorted(tool_counts),
        "priors": dict(tool_counts),
        "token_weights": token_weights,
        "tool_name_tokens": {
            tool: tokenize(tool)
            for tool in sorted(tool_counts)
        },
        "notes": (
            "This is a lightweight BC baseline with multi-label ranking. "
            "It avoids optional ML dependencies so the Discord bot runtime stays stable."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a lightweight tool selector.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_MODEL)
    args = parser.parse_args()

    model = train(_read_jsonl(args.dataset))
    args.output.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Trained on {model['row_count']} rows")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
