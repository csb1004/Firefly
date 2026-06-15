import argparse
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from reward_function import calculate_reward
from train_tool_selector import tokenize


ROOT = Path(__file__).resolve().parent
DEFAULT_TASKS = ROOT / "env_tasks.jsonl"
DEFAULT_MODEL = ROOT / "tool_selector_rl_model.json"
DEFAULT_REPORT = ROOT / "rl_training_report.md"
ACTION_SEPARATOR = " || "


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _expected_tools(row: dict[str, Any]) -> list[str]:
    return list(row.get("expected_tools") or row.get("actions") or [])


def _split_for_index(index: int) -> str:
    bucket = index % 10
    if bucket < 7:
        return "train"
    if bucket < 9:
        return "validation"
    return "test"


def split_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    split_rows_by_name = {"train": [], "validation": [], "test": []}
    for index, row in enumerate(rows):
        split = row.get("split") or _split_for_index(index)
        split_rows_by_name.setdefault(split, []).append(row)
    train_rows = split_rows_by_name.get("train") or rows
    eval_rows = (split_rows_by_name.get("validation") or []) + (split_rows_by_name.get("test") or [])
    if not eval_rows:
        eval_rows = rows
    return train_rows, split_rows_by_name.get("validation") or [], split_rows_by_name.get("test") or eval_rows


def action_key(tools: list[str]) -> str:
    return ACTION_SEPARATOR.join(tools)


def split_action(action: str) -> list[str]:
    return [part for part in action.split(ACTION_SEPARATOR) if part]


def _context_features(context: dict[str, Any] | None) -> list[str]:
    if not context:
        return []
    features = []
    for key, value in sorted(context.items()):
        features.append(f"ctx:{key}")
        if isinstance(value, (str, int, float, bool)) or value is None:
            features.append(f"ctx:{key}={value}")
        elif isinstance(value, list):
            features.extend(f"ctx:{key}={item}" for item in value[:5])
    return features


def features_for(row: dict[str, Any]) -> list[str]:
    features = [f"tok:{token}" for token in tokenize(row.get("user_message", ""))]
    features.extend(_context_features(row.get("context")))
    if row.get("task_type"):
        features.append(f"task:{row['task_type']}")
    if row.get("difficulty"):
        features.append(f"difficulty:{row['difficulty']}")
    return sorted(set(features)) or ["bias:empty"]


def build_action_space(rows: list[dict[str, Any]], max_sequence_actions: int) -> list[str]:
    singles = {
        tool
        for row in rows
        for tool in (row.get("available_tools") or _expected_tools(row))
    }
    sequence_counts = Counter(
        action_key(_expected_tools(row))
        for row in rows
        if len(_expected_tools(row)) > 1
    )
    sequences = [
        key
        for key, _count in sequence_counts.most_common(max_sequence_actions)
    ]
    return sorted(singles) + sorted(sequences)


def _allowed_actions(row: dict[str, Any], action_space: list[str]) -> list[str]:
    available_tools = set(row.get("available_tools") or [])
    if not available_tools:
        return action_space
    allowed = [
        action
        for action in action_space
        if set(split_action(action)).issubset(available_tools)
    ]
    return allowed or action_space


def _candidate_actions(
    row: dict[str, Any],
    action_space: list[str],
    rng: random.Random,
    negative_samples: int,
) -> list[str]:
    allowed = _allowed_actions(row, action_space)
    expected_key = action_key(_expected_tools(row))
    candidates = {expected_key} if expected_key in allowed else set()
    for tool in _expected_tools(row):
        if tool in allowed:
            candidates.add(tool)
    negatives = [action for action in allowed if action not in candidates]
    if negative_samples > 0 and len(negatives) > negative_samples:
        negatives = rng.sample(negatives, negative_samples)
    candidates.update(negatives)
    return sorted(candidates) or allowed


def _score_action(
    model: dict[str, Any],
    features: list[str],
    action: str,
    message: str,
    *,
    name_bonus: bool = True,
) -> float:
    score = float(model.get("bias", {}).get(action, 0.0))
    weights = model.get("feature_weights", {})
    for feature in features:
        score += float(weights.get(feature, {}).get(action, 0.0))

    if not name_bonus:
        return score

    folded_message = message.casefold()
    message_tokens = set(tokenize(message))
    for tool in split_action(action):
        if tool.casefold() in folded_message:
            score += 100.0
        if message_tokens & set(tokenize(tool)):
            score += 5.0
    return score


def predict_with_model(
    model: dict[str, Any],
    user_message: str,
    context: dict[str, Any] | None = None,
    available_tools: list[str] | None = None,
    *,
    top_k: int = 3,
) -> dict[str, Any]:
    row = {
        "user_message": user_message,
        "context": context or {},
        "available_tools": available_tools or model.get("tools", []),
    }
    features = features_for(row)
    action_space = _allowed_actions(row, list(model.get("action_space", [])))
    ranked = sorted(
        (
            {
                "action": action,
                "tools": split_action(action),
                "score": _score_action(model, features, action, user_message),
            }
            for action in action_space
        ),
        key=lambda item: item["score"],
        reverse=True,
    )
    if not ranked:
        return {"selected_tools": [], "confidence": 0.0, "candidate_actions": []}

    top_score = ranked[0]["score"]
    exp_scores = [math.exp(max(-60.0, min(60.0, item["score"] - top_score))) for item in ranked[:top_k]]
    total = sum(exp_scores) or 1.0
    candidates = []
    for item, exp_score in zip(ranked[:top_k], exp_scores):
        candidates.append({
            "action": item["action"],
            "tools": item["tools"],
            "confidence": round(exp_score / total, 4),
        })
    return {
        "selected_tools": candidates[0]["tools"],
        "confidence": candidates[0]["confidence"],
        "candidate_actions": candidates,
    }


def evaluate_model(model: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, float]:
    totals = {
        "top_1": 0,
        "top_3": 0,
        "sequence": 0,
        "multi_tool": 0,
        "ambiguous": 0,
        "context": 0,
        "reward": 0.0,
    }
    counts = {
        "all": len(rows),
        "multi_tool": 0,
        "ambiguous": 0,
        "context": 0,
    }

    for row in rows:
        expected = _expected_tools(row)
        prediction = predict_with_model(
            model,
            row.get("user_message", ""),
            row.get("context"),
            row.get("available_tools"),
        )
        selected = prediction["selected_tools"]
        candidate_tool_sets = [set(item["tools"]) for item in prediction["candidate_actions"]]

        if expected and selected[:1] == expected[:1]:
            totals["top_1"] += 1
        if expected and any(set(expected) & candidate_tools for candidate_tools in candidate_tool_sets):
            totals["top_3"] += 1
        if expected == selected[:len(expected)]:
            totals["sequence"] += 1
        if len(expected) > 1:
            counts["multi_tool"] += 1
            if expected == selected:
                totals["multi_tool"] += 1
        if row.get("is_ambiguous") or row.get("task_type") == "Ambiguous":
            counts["ambiguous"] += 1
            if any(set(expected) & candidate_tools for candidate_tools in candidate_tool_sets):
                totals["ambiguous"] += 1
        if row.get("context") or row.get("task_type") == "Context Dependent":
            counts["context"] += 1
            if any(set(expected) & candidate_tools for candidate_tools in candidate_tool_sets):
                totals["context"] += 1
        totals["reward"] += calculate_reward(expected, selected)

    all_count = max(1, counts["all"])
    return {
        "Top-1 Accuracy": totals["top_1"] / all_count,
        "Top-3 Accuracy": totals["top_3"] / all_count,
        "Sequence Accuracy": totals["sequence"] / all_count,
        "Multi-Tool Accuracy": totals["multi_tool"] / max(1, counts["multi_tool"]),
        "Ambiguous Query Accuracy": totals["ambiguous"] / max(1, counts["ambiguous"]),
        "Context-dependent Accuracy": totals["context"] / max(1, counts["context"]),
        "Average Reward": totals["reward"] / all_count,
        "Evaluated Rows": float(counts["all"]),
    }


def _empty_model(action_space: list[str], tools: list[str], args: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "model_type": "standard-library contextual-bandit q-learning tool selector",
        "action_separator": ACTION_SEPARATOR,
        "action_space": action_space,
        "tools": tools,
        "bias": {},
        "feature_weights": {},
        "hyperparameters": args,
    }


def train(
    rows: list[dict[str, Any]],
    *,
    episodes: int = 40,
    learning_rate: float = 0.2,
    epsilon: float = 0.2,
    epsilon_decay: float = 0.96,
    seed: int = 42,
    max_sequence_actions: int = 250,
    negative_samples: int = 32,
    evaluation_interval: int = 5,
) -> tuple[dict[str, Any], list[dict[str, float]]]:
    rng = random.Random(seed)
    train_rows, validation_rows, test_rows = split_rows(rows)
    action_space = build_action_space(train_rows, max_sequence_actions)
    tools = sorted({
        tool
        for row in rows
        for tool in (row.get("available_tools") or _expected_tools(row))
    })
    model = _empty_model(
        action_space,
        tools,
        {
            "episodes": episodes,
            "learning_rate": learning_rate,
            "epsilon": epsilon,
            "epsilon_decay": epsilon_decay,
            "seed": seed,
            "max_sequence_actions": max_sequence_actions,
            "negative_samples": negative_samples,
            "evaluation_interval": evaluation_interval,
        },
    )
    feature_weights: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    bias: dict[str, float] = defaultdict(float)
    history = []

    for episode in range(1, episodes + 1):
        rng.shuffle(train_rows)
        total_reward = 0.0
        for row in train_rows:
            features = features_for(row)
            candidates = _candidate_actions(row, action_space, rng, negative_samples)
            if rng.random() < epsilon:
                action = rng.choice(candidates)
            else:
                action = max(
                    candidates,
                    key=lambda candidate: _score_action(
                        {"bias": bias, "feature_weights": feature_weights},
                        features,
                        candidate,
                        row.get("user_message", ""),
                        name_bonus=False,
                    ),
                )

            expected = _expected_tools(row)
            reward = calculate_reward(expected, split_action(action))
            current = _score_action(
                {"bias": bias, "feature_weights": feature_weights},
                features,
                action,
                row.get("user_message", ""),
                name_bonus=False,
            )
            error = reward - current
            feature_step = learning_rate * error / max(1, len(features))
            for feature in features:
                feature_weights[feature][action] += feature_step
            bias[action] += learning_rate * error
            total_reward += reward

        model["bias"] = {key: round(value, 6) for key, value in bias.items()}
        model["feature_weights"] = {
            feature: {action: round(value, 6) for action, value in weights.items()}
            for feature, weights in feature_weights.items()
        }
        should_evaluate = episode == episodes or (
            evaluation_interval > 0 and episode % evaluation_interval == 0
        )
        metrics = (
            evaluate_model(model, validation_rows or test_rows or train_rows)
            if should_evaluate
            else {"Average Reward": 0.0, "Sequence Accuracy": 0.0}
        )
        history.append({
            "episode": float(episode),
            "epsilon": epsilon,
            "train_average_reward": total_reward / max(1, len(train_rows)),
            "validation_average_reward": metrics["Average Reward"],
            "validation_sequence_accuracy": metrics["Sequence Accuracy"],
        })
        epsilon *= epsilon_decay

    model["training_rows"] = len(train_rows)
    model["validation_rows"] = len(validation_rows)
    model["test_rows"] = len(test_rows)
    model["training_history"] = history[-10:]
    model["validation_metrics"] = evaluate_model(model, validation_rows or train_rows)
    model["test_metrics"] = evaluate_model(model, test_rows or validation_rows or train_rows)
    return model, history


def write_report(model: dict[str, Any], history: list[dict[str, float]], path: Path) -> None:
    validation = model.get("validation_metrics", {})
    test = model.get("test_metrics", {})
    lines = [
        "# RL Tool Selector Training Report",
        "",
        f"- Model: `{model['model_type']}`",
        f"- Training rows: {model['training_rows']}",
        f"- Validation rows: {model['validation_rows']}",
        f"- Test rows: {model['test_rows']}",
        f"- Actions: {len(model['action_space'])}",
        "",
        "## Validation Metrics",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key, value in validation.items():
        lines.append(f"| {key} | {int(value) if key == 'Evaluated Rows' else f'{value:.2%}'} |")
    lines.extend([
        "",
        "## Test Metrics",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ])
    for key, value in test.items():
        lines.append(f"| {key} | {int(value) if key == 'Evaluated Rows' else f'{value:.2%}'} |")
    lines.extend([
        "",
        "## Last Episodes",
        "",
        "| Episode | Epsilon | Train Avg Reward | Validation Avg Reward | Validation Sequence Accuracy |",
        "| ---: | ---: | ---: | ---: | ---: |",
    ])
    for item in history[-10:]:
        lines.append(
            f"| {int(item['episode'])} | {item['epsilon']:.4f} | "
            f"{item['train_average_reward']:.2%} | {item['validation_average_reward']:.2%} | "
            f"{item['validation_sequence_accuracy']:.2%} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a reward-based tool selector policy.")
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--output", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--episodes", type=int, default=40)
    parser.add_argument("--learning-rate", type=float, default=0.2)
    parser.add_argument("--epsilon", type=float, default=0.2)
    parser.add_argument("--epsilon-decay", type=float, default=0.96)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-sequence-actions", type=int, default=250)
    parser.add_argument("--negative-samples", type=int, default=32)
    parser.add_argument("--evaluation-interval", type=int, default=5)
    args = parser.parse_args()

    model, history = train(
        _read_jsonl(args.tasks),
        episodes=args.episodes,
        learning_rate=args.learning_rate,
        epsilon=args.epsilon,
        epsilon_decay=args.epsilon_decay,
        seed=args.seed,
        max_sequence_actions=args.max_sequence_actions,
        negative_samples=args.negative_samples,
        evaluation_interval=args.evaluation_interval,
    )
    args.output.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_report(model, history, args.report)
    print(f"Trained RL policy on {model['training_rows']} rows for {args.episodes} episodes")
    print(f"Validation reward: {model['validation_metrics']['Average Reward']:.4f}")
    print(f"Test reward: {model['test_metrics']['Average Reward']:.4f}")
    print(f"Wrote {args.output}")
    print(f"Wrote {args.report}")


if __name__ == "__main__":
    main()
