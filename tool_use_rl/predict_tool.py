import json
from pathlib import Path
from typing import Any

try:
    from .train_tool_selector import tokenize
except ImportError:
    from train_tool_selector import tokenize


ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL = ROOT / "tool_selector_model.json"


def _load_model(model_path: Path) -> dict[str, Any] | None:
    if not model_path.exists():
        return None
    try:
        return json.loads(model_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _rank_with_model(user_message: str, model: dict[str, Any]) -> list[dict[str, Any]]:
    priors = model.get("priors", {})
    token_weights = model.get("token_weights", {})
    scores = {tool: float(count) * 0.05 for tool, count in priors.items()}

    for token in set(tokenize(user_message)):
        for tool, weight in token_weights.get(token, {}).items():
            scores[tool] = scores.get(tool, 0.0) + float(weight)

    message_tokens = set(tokenize(user_message))
    folded_message = user_message.casefold()
    for tool, name_tokens in model.get("tool_name_tokens", {}).items():
        if message_tokens & set(name_tokens):
            scores[tool] = scores.get(tool, 0.0) + 5.0 * len(message_tokens & set(name_tokens))
        if tool.casefold() in folded_message:
            scores[tool] = scores.get(tool, 0.0) + 100.0

    if not scores:
        return []
    max_score = max(scores.values()) or 1.0
    return [
        {"tool": tool, "confidence": round(score / max_score, 4)}
        for tool, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)
    ]


def select_tool(
    user_message: str,
    context: dict | None = None,
    *,
    model_path: Path = DEFAULT_MODEL,
) -> dict[str, Any]:
    model = _load_model(model_path)
    if model is None:
        return {
            "selected_tools": [],
            "confidence": 0.0,
            "candidate_tools": [],
        }

    candidates = _rank_with_model(user_message, model)
    selected = [
        candidate["tool"]
        for candidate in candidates
        if candidate["confidence"] >= 0.45
    ][:3]

    if not selected and candidates:
        selected = [candidates[0]["tool"]]

    return {
        "selected_tools": selected,
        "confidence": candidates[0]["confidence"] if candidates else 0.0,
        "candidate_tools": candidates[:3],
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Predict tool(s) for a user message.")
    parser.add_argument("message")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    args = parser.parse_args()
    print(json.dumps(select_tool(args.message, model_path=args.model), ensure_ascii=False, indent=2))
