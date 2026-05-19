from .config import DAILY_NEWS_KEY, POLLS_KEY, ROOMS_KEY
from .voice import get_active_recording
from .voice_records import list_recordings


def _count_user_entries(memory: dict) -> int:
    return sum(1 for key, value in memory.items() if key.isdigit() and isinstance(value, dict))


def _count_room_entries(memory: dict) -> int:
    rooms = memory.get(ROOMS_KEY, {})
    return len(rooms) if isinstance(rooms, dict) else 0


def _count_room_messages(memory: dict) -> int:
    rooms = memory.get(ROOMS_KEY, {})
    if not isinstance(rooms, dict):
        return 0
    return sum(
        len(room.get("history", []))
        for room in rooms.values()
        if isinstance(room, dict)
    )


def build_admin_status_text(
    memory: dict,
    *,
    current_room_key: str,
    current_room_data: dict,
    guild_id: int | None = None,
) -> str:
    polls = memory.get(POLLS_KEY, {})
    news = memory.get(DAILY_NEWS_KEY, {})
    subscribers = news.get("subscribers", {}) if isinstance(news, dict) else {}
    topics = news.get("topics", []) if isinstance(news, dict) else []
    recordings = list_recordings()
    active_recording = get_active_recording(guild_id) if guild_id is not None else None

    lines = [
        "Bot status",
        f"- users: {_count_user_entries(memory)}",
        f"- rooms: {_count_room_entries(memory)}",
        f"- room messages: {_count_room_messages(memory)}",
        f"- active polls: {len(polls) if isinstance(polls, dict) else 0}",
        f"- news subscribers: {len(subscribers) if isinstance(subscribers, dict) else 0}",
        f"- news topics: {len(topics) if isinstance(topics, list) else 0}",
        f"- saved voice recordings: {len(recordings)}",
        f"- active voice recording: {'yes' if active_recording else 'no'}",
        f"- current room key: {current_room_key}",
        f"- current room internet mode: {'on' if current_room_data.get('internet_mode') else 'off'}",
        f"- current room group mode: {'on' if current_room_data.get('group_mode') else 'off'}",
        f"- current room history: {len(current_room_data.get('history', []))}",
    ]
    return "\n".join(lines)
