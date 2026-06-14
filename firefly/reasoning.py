REASONING_EFFORT_KEY = "reasoning_effort"
DEFAULT_REASONING_EFFORT = "medium"
VALID_REASONING_EFFORTS = ("none", "low", "medium", "high")

REASONING_EFFORT_LABELS = {
    "none": "없음",
    "low": "낮음",
    "medium": "보통",
    "high": "높음",
}

REASONING_EFFORT_ALIASES = {
    "0": "none",
    "off": "none",
    "none": "none",
    "no": "none",
    "없음": "none",
    "끄기": "none",
    "꺼": "none",
    "1": "low",
    "low": "low",
    "낮음": "low",
    "낮게": "low",
    "약함": "low",
    "가볍게": "low",
    "2": "medium",
    "medium": "medium",
    "mid": "medium",
    "normal": "medium",
    "보통": "medium",
    "중간": "medium",
    "기본": "medium",
    "일반": "medium",
    "3": "high",
    "high": "high",
    "높음": "high",
    "높게": "high",
    "강함": "high",
    "깊게": "high",
}


def normalize_reasoning_effort(raw_value: object) -> str | None:
    value = str(raw_value or "").strip().casefold()
    return REASONING_EFFORT_ALIASES.get(value)


def normalize_room_reasoning_effort(room_data: dict) -> str:
    effort = room_data.get(REASONING_EFFORT_KEY, DEFAULT_REASONING_EFFORT)
    if effort not in VALID_REASONING_EFFORTS:
        effort = DEFAULT_REASONING_EFFORT
    room_data[REASONING_EFFORT_KEY] = effort
    return effort


def set_room_reasoning_effort(room_data: dict, raw_value: object) -> str | None:
    effort = normalize_reasoning_effort(raw_value)
    if effort is None:
        return None
    room_data[REASONING_EFFORT_KEY] = effort
    return effort


def reasoning_effort_label(effort: str) -> str:
    return REASONING_EFFORT_LABELS.get(effort, REASONING_EFFORT_LABELS[DEFAULT_REASONING_EFFORT])


def format_reasoning_status(room_data: dict) -> str:
    effort = normalize_room_reasoning_effort(room_data)
    return f"{reasoning_effort_label(effort)} ({effort})"
