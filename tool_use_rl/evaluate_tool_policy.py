import argparse
import json
from pathlib import Path
from typing import Any

try:
    from .predict_tool import DEFAULT_MODEL, select_tool
    from .reward_function import calculate_reward
except ImportError:
    from predict_tool import DEFAULT_MODEL, select_tool
    from reward_function import calculate_reward


ROOT = Path(__file__).resolve().parent
DEFAULT_DATASET = ROOT / "synthetic_tool_dataset.jsonl"
DEFAULT_REPORT = ROOT / "evaluation_report.md"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def evaluate(rows: list[dict[str, Any]], model_path: Path) -> dict[str, float]:
    eval_rows = [row for row in rows if row.get("split") in {"validation", "test"}] or rows
    totals = {
        "top_1": 0,
        "top_3": 0,
        "multi_tool": 0,
        "sequence": 0,
        "ambiguous": 0,
        "context": 0,
        "reward": 0.0,
    }
    counts = {
        "all": len(eval_rows),
        "multi_tool": 0,
        "ambiguous": 0,
        "context": 0,
    }

    for row in eval_rows:
        expected = row.get("actions", [])
        prediction = select_tool(row["user_message"], row.get("context"), model_path=model_path)
        selected = prediction["selected_tools"]
        candidates = [item["tool"] for item in prediction["candidate_tools"]]

        if expected and selected[:1] == expected[:1]:
            totals["top_1"] += 1
        if expected and any(action in candidates[:3] for action in expected):
            totals["top_3"] += 1
        if len(expected) > 1:
            counts["multi_tool"] += 1
            if set(expected) == set(selected):
                totals["multi_tool"] += 1
        if expected == selected[:len(expected)]:
            totals["sequence"] += 1
        if row.get("is_ambiguous"):
            counts["ambiguous"] += 1
            if set(expected) & set(candidates[:3]):
                totals["ambiguous"] += 1
        if row.get("context"):
            counts["context"] += 1
            if set(expected) & set(candidates[:3]):
                totals["context"] += 1
        totals["reward"] += calculate_reward(expected, selected)

    all_count = max(1, counts["all"])
    return {
        "Top-1 Accuracy": totals["top_1"] / all_count,
        "Top-3 Accuracy": totals["top_3"] / all_count,
        "Multi-Tool Accuracy": totals["multi_tool"] / max(1, counts["multi_tool"]),
        "Sequence Accuracy": totals["sequence"] / all_count,
        "Ambiguous Query Accuracy": totals["ambiguous"] / max(1, counts["ambiguous"]),
        "Context-dependent Accuracy": totals["context"] / max(1, counts["context"]),
        "Average Reward": totals["reward"] / all_count,
        "Evaluated Rows": float(counts["all"]),
    }


def write_report(metrics: dict[str, float], path: Path) -> None:
    lines = [
        "# Evaluation Report",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key, value in metrics.items():
        if key == "Evaluated Rows":
            lines.append(f"| {key} | {int(value)} |")
        else:
            lines.append(f"| {key} | {value:.2%} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate tool selector policy.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    metrics = evaluate(_read_jsonl(args.dataset), args.model)
    write_report(metrics, args.report)
    for key, value in metrics.items():
        print(f"{key}: {value:.4f}" if key != "Evaluated Rows" else f"{key}: {int(value)}")
    print(f"Wrote {args.report}")


if __name__ == "__main__":
    main()
