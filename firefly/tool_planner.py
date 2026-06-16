import json
import re
from dataclasses import dataclass
from typing import Any


PLAN_CHAT = "chat"
PLAN_COMMAND = "command"
PLAN_COMMAND_THEN_REPLY = "command_then_reply"
PLAN_CLARIFY = "clarify"
PLAN_REJECT = "reject"
PLAN_MODES = {
    PLAN_CHAT,
    PLAN_COMMAND,
    PLAN_COMMAND_THEN_REPLY,
    PLAN_CLARIFY,
    PLAN_REJECT,
}


@dataclass(frozen=True)
class ToolPlan:
    mode: str
    commands: tuple[str, ...] = ()
    response: str = ""
    confidence: float = 0.0


def _extract_json_object(text: str) -> str | None:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1)

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        return stripped[start : end + 1]
    return None


def parse_tool_plan(text: str) -> ToolPlan | None:
    raw_json = _extract_json_object(text)
    if raw_json is None:
        return None

    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    mode = str(payload.get("mode") or PLAN_CHAT).strip()
    if mode not in PLAN_MODES:
        return None

    commands = payload.get("commands") or []
    if isinstance(commands, str):
        commands = [commands]
    if not isinstance(commands, list):
        commands = []

    normalized_commands = []
    for command in commands:
        if not isinstance(command, str):
            continue
        command = command.strip()
        if command.startswith("/") and command != "/":
            normalized_commands.append(command[:1900])

    response = str(payload.get("response") or payload.get("question") or "").strip()
    try:
        confidence = float(payload.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    if mode in {PLAN_COMMAND, PLAN_COMMAND_THEN_REPLY} and not normalized_commands:
        return None
    if mode in {PLAN_CLARIFY, PLAN_REJECT} and not response:
        return None

    return ToolPlan(
        mode=mode,
        commands=tuple(normalized_commands),
        response=response[:1900],
        confidence=max(0.0, min(1.0, confidence)),
    )


def serialize_tool_plan(plan: ToolPlan) -> dict[str, Any]:
    return {
        "mode": plan.mode,
        "commands": list(plan.commands),
        "response": plan.response,
        "confidence": plan.confidence,
    }
