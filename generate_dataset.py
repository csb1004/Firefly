import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_SCHEMA = ROOT / "tools_schema.json"
DEFAULT_OUTPUT = ROOT / "synthetic_tool_dataset.jsonl"

DIFFICULTIES = ("easy", "medium", "hard", "ambiguous", "multi-tool", "context-dependent")
REQUEST_STYLES = (
    "direct request",
    "indirect request",
    "typo",
    "slang",
    "abbreviated request",
    "context-driven request",
)


def _load_tools(path: Path) -> list[dict[str, Any]]:
    schema = json.loads(path.read_text(encoding="utf-8"))
    tools = schema.get("tools", [])
    return [tool for tool in tools if tool.get("name") and tool.get("aliases")]


def _stable_id(seed: int, index: int, user_message: str) -> str:
    digest = hashlib.sha1(f"{seed}:{index}:{user_message}".encode("utf-8")).hexdigest()[:12]
    return f"synthetic-{digest}"


def _split_for_index(index: int) -> str:
    bucket = index % 10
    if bucket < 7:
        return "train"
    if bucket < 9:
        return "validation"
    return "test"


def _alias_without_slash(tool: dict[str, Any], rng: random.Random) -> str:
    alias = rng.choice(tool.get("aliases") or [tool["name"]])
    return alias.lstrip("/")


def _description_fragment(tool: dict[str, Any]) -> str:
    description = str(tool.get("description") or "").strip()
    if not description:
        return tool["name"]
    return description.rstrip(".")


def _mutate_text(text: str, rng: random.Random) -> str:
    if len(text) < 4:
        return text
    chars = list(text)
    operation = rng.choice(("drop", "swap", "space"))
    if operation == "drop":
        index = rng.randrange(len(chars))
        del chars[index]
    elif operation == "swap" and len(chars) > 5:
        index = rng.randrange(len(chars) - 1)
        chars[index], chars[index + 1] = chars[index + 1], chars[index]
    else:
        index = rng.randrange(1, len(chars))
        chars.insert(index, " ")
    return "".join(chars)


def _context_for(tool: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    return {
        "room_mode": rng.choice(["dm", "guild", "group"]),
        "recent_tool": rng.choice(tool.get("related_tools") or [None]),
        "special_user": tool.get("type") in {"slash_command", "prefix_command"},
    }


def _single_tool_message(tool: dict[str, Any], difficulty: str, style: str, rng: random.Random) -> str:
    alias = _alias_without_slash(tool, rng)
    description = _description_fragment(tool)
    name = tool["name"]

    if style == "direct request":
        return rng.choice([
            f"{alias} 실행해줘",
            f"{name} 명령으로 처리해줘",
            f"{alias}로 해줘",
        ])
    if style == "indirect request":
        return rng.choice([
            f"{description} 상황이야. 알아서 처리해줘",
            f"이 요청은 {description} 기능이 필요해 보여",
            f"{name} 쪽 기능으로 해결하면 될 것 같아",
        ])
    if style == "typo":
        return _mutate_text(f"{alias} 해줘", rng)
    if style == "slang":
        return rng.choice([
            f"{name} ㄱㄱ",
            f"{alias} ㄱ",
            f"{name} 바로 가자",
        ])
    if style == "abbreviated request":
        compact = "".join(part[0] for part in name.split() if part)
        return f"{compact or name[:2]} 처리"
    return rng.choice([
        f"아까 말한 흐름 이어서 {name} 해줘",
        f"방금 결과 기준으로 {alias} 부탁해",
        f"이 방 문맥 보고 {description} 쪽으로 처리해",
    ])


def _multi_tool_message(tools: list[dict[str, Any]], rng: random.Random) -> str:
    names = [_alias_without_slash(tool, rng) for tool in tools]
    return rng.choice([
        f"{names[0]} 먼저 하고 그 결과로 {names[1]}까지 이어서 해줘",
        f"{names[0]} && {names[1]} 순서로 처리한 다음 답해줘",
        f"{tools[0]['name']} 결과를 보고 {tools[1]['name']}도 같이 해줘",
    ])


def generate_dataset(tools: list[dict[str, Any]], samples: int, seed: int) -> list[dict[str, Any]]:
    if not tools:
        raise ValueError("tools_schema.json에 도구가 없어 데이터셋을 만들 수 없습니다.")

    rng = random.Random(seed)
    rows = []
    for index in range(samples):
        difficulty = DIFFICULTIES[index % len(DIFFICULTIES)]
        style = REQUEST_STYLES[(index + rng.randrange(len(REQUEST_STYLES))) % len(REQUEST_STYLES)]
        is_multi = difficulty == "multi-tool" or (len(tools) > 1 and rng.random() < 0.18)
        is_ambiguous = difficulty == "ambiguous"
        is_context = difficulty == "context-dependent" or style == "context-driven request"

        if is_multi:
            selected = rng.sample(tools, k=min(2, len(tools)))
            user_message = _multi_tool_message(selected, rng)
        else:
            selected = [rng.choice(tools)]
            user_message = _single_tool_message(selected[0], difficulty, style, rng)

        if is_ambiguous:
            user_message = rng.choice([
                "이거 처리해줘. 무슨 기능이 맞는지는 애매해",
                f"{selected[0]['name']}인지 관련 기능인지 헷갈리는데 맞게 골라줘",
                "방금 말한 걸 봐서 필요한 도구로 실행해줘",
            ])

        if rng.random() < 0.25:
            user_message = f"반디야, {user_message}"

        context = _context_for(selected[0], rng) if is_context else {}
        row = {
            "id": _stable_id(seed, index, user_message),
            "user_message": user_message,
            "actions": [tool["name"] for tool in selected],
            "difficulty": difficulty,
            "is_ambiguous": is_ambiguous,
            "context": context,
            "reason": f"schema-driven {style}; source={', '.join(tool['source_file'] for tool in selected)}",
            "split": _split_for_index(index),
        }
        rows.append(row)
    return rows


def _write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def _print_stats(rows: list[dict[str, Any]]) -> None:
    tool_counts = Counter(action for row in rows for action in row["actions"])
    difficulty_counts = Counter(row["difficulty"] for row in rows)
    split_counts = Counter(row["split"] for row in rows)
    multi = sum(1 for row in rows if len(row["actions"]) > 1)
    context = sum(1 for row in rows if row["context"])
    ambiguous = sum(1 for row in rows if row["is_ambiguous"])
    total = max(1, len(rows))

    print("Tool distribution:", dict(tool_counts))
    print("Difficulty distribution:", dict(difficulty_counts))
    print("Split distribution:", dict(split_counts))
    print(f"Multi-tool ratio: {multi / total:.2%}")
    print(f"Context-dependent ratio: {context / total:.2%}")
    print(f"Ambiguous ratio: {ambiguous / total:.2%}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic tool-use training data.")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--samples", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rows = generate_dataset(_load_tools(args.schema), args.samples, args.seed)
    _write_jsonl(rows, args.output)
    _print_stats(rows)
    print(f"Wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
