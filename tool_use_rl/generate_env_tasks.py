import argparse
import json
import random
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_SCHEMA = ROOT / "tools_schema.json"
DEFAULT_OUTPUT = ROOT / "env_tasks.jsonl"


TASK_TYPES = ("Single Tool", "Multi Tool", "Ambiguous", "Context Dependent")


def _load_tools(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8")).get("tools", [])


def generate_tasks(tools: list[dict[str, Any]], count: int, seed: int) -> list[dict[str, Any]]:
    if not tools:
        raise ValueError("tools_schema.json에 도구가 없어 task를 만들 수 없습니다.")
    rng = random.Random(seed)
    names = [tool["name"] for tool in tools]
    tasks = []
    for index in range(count):
        task_type = TASK_TYPES[index % len(TASK_TYPES)]
        if task_type == "Multi Tool" and len(names) > 1:
            expected = rng.sample(names, 2)
            message = f"{expected[0]} 결과를 확인한 뒤 {expected[1]}도 이어서 실행"
        else:
            expected = [rng.choice(names)]
            if task_type == "Ambiguous":
                message = "문맥상 필요한 도구를 골라서 처리"
            elif task_type == "Context Dependent":
                message = f"방금 흐름을 보고 {expected[0]} 처리"
            else:
                message = f"{expected[0]} 실행"
        context = {"recent_tool": rng.choice(names)} if task_type == "Context Dependent" else {}
        tasks.append({
            "id": f"env-task-{seed}-{index}",
            "task_type": task_type,
            "user_message": message,
            "context": context,
            "available_tools": names,
            "expected_tools": expected,
        })
    return tasks


def _write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate executable tool environment tasks.")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--tasks", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rows = generate_tasks(_load_tools(args.schema), args.tasks, args.seed)
    _write_jsonl(rows, args.output)
    print(f"Wrote {len(rows)} tasks to {args.output}")


if __name__ == "__main__":
    main()
