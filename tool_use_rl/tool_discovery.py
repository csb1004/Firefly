import ast
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ARTIFACT_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ARTIFACT_ROOT.parent
SCHEMA_PATH = ARTIFACT_ROOT / "tools_schema.json"
REPORT_PATH = ARTIFACT_ROOT / "tool_discovery_report.md"


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _decorator_call_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Attribute):
        owner = getattr(func.value, "id", None)
        return f"{owner}.{func.attr}" if owner else func.attr
    return getattr(func, "id", None)


def _keyword_value(call: ast.Call, name: str) -> str | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return _literal_string(keyword.value)
    return None


def _group_prefix(call_name: str) -> str:
    if call_name == "news_group.command":
        return "최신소식"
    if call_name == "topic_group.command":
        return "주제"
    return ""


def _source_path(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def _arguments_from_function(node: ast.AsyncFunctionDef | ast.FunctionDef) -> list[dict[str, Any]]:
    args = []
    for arg in node.args.args:
        if arg.arg in {"interaction", "message", "client", "self"}:
            continue
        args.append({
            "name": arg.arg,
            "required": True,
            "description": "",
        })
    return args


def discover_slash_commands(path: Path = PROJECT_ROOT / "Firefly.py") -> list[dict[str, Any]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    tools: list[dict[str, Any]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for decorator in node.decorator_list:
            call_name = _decorator_call_name(decorator)
            if call_name not in {"tree.command", "news_group.command", "topic_group.command"}:
                continue
            assert isinstance(decorator, ast.Call)
            name = _keyword_value(decorator, "name")
            description = _keyword_value(decorator, "description") or ""
            if not name:
                continue

            prefix = _group_prefix(call_name)
            full_name = f"{prefix} {name}".strip()
            tools.append({
                "name": full_name,
                "aliases": [f"/{full_name}"],
                "type": "slash_command",
                "description": description,
                "arguments": _arguments_from_function(node),
                "source_file": f"{_source_path(path)}:{node.lineno}",
                "confidence": 1.0,
                "dependencies": _infer_dependencies(full_name, description),
                "related_tools": [],
            })
    return tools


def discover_registered_text_commands(
    path: Path = PROJECT_ROOT / "firefly" / "command_registry.py",
) -> list[dict[str, Any]]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    tools: list[dict[str, Any]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not node.targets:
            continue
        if not isinstance(node.value, ast.Call):
            continue
        if getattr(node.value.func, "id", "") != "TextCommandSpec":
            continue
        aliases: list[str] = []
        summary = ""
        special_only = False
        for keyword in node.value.keywords:
            if keyword.arg == "aliases" and isinstance(keyword.value, ast.Tuple):
                aliases = [
                    item.value
                    for item in keyword.value.elts
                    if isinstance(item, ast.Constant) and isinstance(item.value, str)
                ]
            elif keyword.arg == "summary":
                summary = _literal_string(keyword.value) or ""
            elif keyword.arg == "special_only":
                special_only = bool(getattr(keyword.value, "value", False))

        if not aliases:
            continue
        name = aliases[0].lstrip("/")
        tools.append({
            "name": name,
            "aliases": aliases,
            "type": "prefix_command",
            "description": summary,
            "arguments": [{"name": "text", "required": False, "description": "Command argument text."}],
            "source_file": f"{_source_path(path)}:{node.lineno}",
            "confidence": 1.0,
            "dependencies": ["firefly.commands"] if special_only else [],
            "related_tools": [],
        })
    return tools


def discover_command_literals(path: Path = PROJECT_ROOT / "firefly" / "commands.py") -> list[dict[str, Any]]:
    source = path.read_text(encoding="utf-8")
    commands = {}
    for match in re.finditer(r"matches_command\(user_text,\s*[\"']([^\"']+)[\"']\)", source):
        command = match.group(1)
        line = source[:match.start()].count("\n") + 1
        commands.setdefault(command, line)

    tools = []
    for command, line in sorted(commands.items()):
        name = command.lstrip("/")
        tools.append({
            "name": name,
            "aliases": [command],
            "type": "prefix_command",
            "description": f"Text command handled by firefly.commands for `{command}`.",
            "arguments": [{"name": "text", "required": False, "description": "Command argument text."}],
            "source_file": f"{_source_path(path)}:{line}",
            "confidence": 0.7,
            "dependencies": _infer_dependencies(name, ""),
            "related_tools": [],
        })
    return tools


def _infer_dependencies(name: str, description: str) -> list[str]:
    text = f"{name} {description}".casefold()
    dependencies = []
    mapping = {
        "투표": "firefly.polls",
        "poll": "firefly.polls",
        "뇌": "firefly.brain",
        "메모리": "firefly.storage",
        "기억": "firefly.storage",
        "최신소식": "firefly.news",
        "뉴스": "firefly.news",
        "주제": "firefly.news",
        "역할": "firefly.role_commands",
        "녹음": "firefly.voice_search",
        "기록": "firefly.voice",
        "요약": "firefly.ai",
        "검색": "firefly.ai",
    }
    for keyword, dependency in mapping.items():
        if keyword.casefold() in text and dependency not in dependencies:
            dependencies.append(dependency)
    return dependencies


def _dedupe_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for tool in tools:
        key = tool["name"].casefold()
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = tool
            continue
        existing["aliases"] = sorted(set(existing["aliases"]) | set(tool["aliases"]))
        existing["confidence"] = max(float(existing["confidence"]), float(tool["confidence"]))
        existing["dependencies"] = sorted(set(existing["dependencies"]) | set(tool["dependencies"]))
        if tool["type"] == "slash_command":
            existing["type"] = "slash_command"
            existing["description"] = tool["description"] or existing["description"]
            existing["arguments"] = tool["arguments"] or existing["arguments"]
            existing["source_file"] = tool["source_file"]
    return sorted(deduped.values(), key=lambda item: item["name"])


def _attach_related_tools(tools: list[dict[str, Any]]) -> None:
    by_dependency: dict[str, list[str]] = {}
    for tool in tools:
        for dependency in tool.get("dependencies", []):
            by_dependency.setdefault(dependency, []).append(tool["name"])
    for tool in tools:
        related = set()
        for dependency in tool.get("dependencies", []):
            related.update(by_dependency.get(dependency, []))
        related.discard(tool["name"])
        tool["related_tools"] = sorted(related)[:8]


def discover_tools() -> dict[str, list[dict[str, Any]]]:
    tools = _dedupe_tools(
        discover_slash_commands()
        + discover_registered_text_commands()
        + discover_command_literals()
    )
    _attach_related_tools(tools)
    return {"tools": tools}


def write_schema(schema: dict[str, Any], path: Path = SCHEMA_PATH) -> None:
    path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_report(schema: dict[str, Any], path: Path = REPORT_PATH) -> None:
    tools = schema["tools"]
    type_counts = Counter(tool["type"] for tool in tools)
    lines = [
        "# Tool Discovery Report",
        "",
        "## Project Structure",
        "- Entry point: `Firefly.py`",
        "- Bot initialization: `discord.Client`, `app_commands.CommandTree`, and `on_ready` in `Firefly.py`",
        "- Slash command registration: decorators on `tree`, `news_group`, and `topic_group` in `Firefly.py`",
        "- Text command router: `firefly.commands.handle_mentioned_message`",
        "- Command guide prompts: `prompt_commands_general.txt` and `prompt_commands_special.txt`",
        "- Service modules: `firefly.polls`, `firefly.brain`, `firefly.news`, `firefly.role_commands`, `firefly.voice`, `firefly.voice_search`, `firefly.storage`",
        "",
        "## Discovery Method",
        "- Parsed `Firefly.py` decorators for real slash commands.",
        "- Parsed `firefly.command_registry` for registered text command aliases.",
        "- Parsed literal `matches_command(user_text, ...)` calls in `firefly.commands` for prefix handlers.",
        "- Kept confidence lower for regex-discovered prefix handlers because descriptions are inferred from handler location.",
        "",
        "## Tool Type Distribution",
    ]
    lines.extend(f"- {tool_type}: {count}" for tool_type, count in sorted(type_counts.items()))
    lines.extend([
        "",
        f"## Discovered Tools ({len(tools)})",
        "",
        "| Name | Type | Confidence | Source | Dependencies |",
        "| --- | --- | ---: | --- | --- |",
    ])
    for tool in tools:
        dependencies = ", ".join(tool.get("dependencies", [])) or "-"
        lines.append(
            f"| {tool['name']} | {tool['type']} | {float(tool['confidence']):.1f} | "
            f"`{tool['source_file']}` | {dependencies} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    schema = discover_tools()
    write_schema(schema)
    write_report(schema)
    print(f"Discovered {len(schema['tools'])} tools")
    print(f"Wrote {SCHEMA_PATH.name}")
    print(f"Wrote {REPORT_PATH.name}")


if __name__ == "__main__":
    main()
