from datetime import datetime, timedelta

from .storage import add_history

RELATIONSHIP_EVENTS_KEY = "relationship_events"


def _parse_seen_at(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _topic_from_message(message: str) -> str | None:
    words = [
        word.strip(".,!?()[]{}\"'")
        for word in message.split()
        if len(word.strip(".,!?()[]{}\"'")) >= 2
    ]
    if not words:
        return None
    return " ".join(words[:8])


def normalize_relationship_events(user_data: dict, now: datetime) -> dict:
    events = user_data.get(RELATIONSHIP_EVENTS_KEY)
    if not isinstance(events, dict):
        events = {}
        user_data[RELATIONSHIP_EVENTS_KEY] = events

    events.setdefault("first_seen_date", now.date().isoformat())
    events.setdefault("last_idle_event_date", None)
    events.setdefault("last_anniversary_year", None)
    events.setdefault("recent_topic", None)
    return events


def build_relationship_event_context(
    user_data: dict,
    user_message: str,
    *,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now()
    events = normalize_relationship_events(user_data, now)
    notes = []

    last_seen = _parse_seen_at(user_data.get("last_seen"))
    today = now.date().isoformat()
    if last_seen is not None:
        idle_days = (now.date() - last_seen.date()).days
        if idle_days >= 7 and events.get("last_idle_event_date") != today:
            notes.append(
                f"- The user has been away for about {idle_days} days. Let the reply subtly feel like a warm reunion, without guilt-tripping."
            )
            events["last_idle_event_date"] = today
        elif idle_days >= 2 and events.get("last_idle_event_date") != today:
            notes.append(
                f"- The user has been away for {idle_days} days. A small 'it's been a bit' feeling is appropriate if it fits."
            )
            events["last_idle_event_date"] = today

    first_seen = _parse_seen_at(events.get("first_seen_date"))
    if first_seen is not None and now.date() > first_seen.date():
        years = now.year - first_seen.year
        same_month_day = (now.month, now.day) == (first_seen.month, first_seen.day)
        if years >= 1 and same_month_day and events.get("last_anniversary_year") != now.year:
            notes.append(
                f"- Today is about {years} year(s) since the first saved conversation with this user. Mention it only if it can feel natural."
            )
            events["last_anniversary_year"] = now.year

    recent_topic = events.get("recent_topic")
    if recent_topic:
        notes.append(
            f"- Recent topic to remember lightly if relevant: {recent_topic}"
        )

    topic = _topic_from_message(user_message)
    if topic and not user_message.startswith("/"):
        events["recent_topic"] = topic

    if not notes:
        return ""

    return "\n".join(["[Relationship/event cues]", *notes])


def record_relationship_event(
    user_data: dict,
    role: str,
    content: str,
) -> dict:
    return add_history(user_data, role, content, event_type="relationship")
