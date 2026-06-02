import json
import re
from threading import RLock

import discord

from .config import (
    BOT_DISPLAY_NAME,
    DAILY_NEWS_KEY,
    DEFAULT_AFFECTION,
    MAX_HISTORY,
    MAX_ROOM_HISTORY,
    MEMORY_FILE,
    POLLS_KEY,
    ROOMS_KEY,
    SPECIAL_USER_ID,
    SPECIAL_USER_NAME,
    SPECIAL_USER_NICKNAME,
)
from .text_utils import clean_discord_content, get_current_time_text

_MEMORY_LOCK = RLock()

MEMORY_SECTION_FILES = {
    "conversation": "conversation_memory.json",
    "rooms": "room_memory.json",
    "polls": "poll_memory.json",
    "news": "news_memory.json",
}
MEMORY_SECTION_LABELS = {
    "conversation": "대화",
    "rooms": "방",
    "polls": "투표",
    "news": "뉴스",
}
MEMORY_SECTION_DATA_KEYS = {
    "rooms": ROOMS_KEY,
    "polls": POLLS_KEY,
    "news": DAILY_NEWS_KEY,
}
MEMORY_SECTION_ALIASES = {
    "대화": "conversation",
    "대화 메모리": "conversation",
    "대화메모리": "conversation",
    "개인": "conversation",
    "개인 기억": "conversation",
    "개인기억": "conversation",
    "유저": "conversation",
    "사용자": "conversation",
    "conversation": "conversation",
    "conversation_memory": "conversation",
    "conversation_memory.json": "conversation",
    "방": "rooms",
    "방 메모리": "rooms",
    "방메모리": "rooms",
    "방 기억": "rooms",
    "방기억": "rooms",
    "룸": "rooms",
    "rooms": "rooms",
    "room": "rooms",
    "room_memory": "rooms",
    "room_memory.json": "rooms",
    "투표": "polls",
    "투표 메모리": "polls",
    "투표메모리": "polls",
    "poll": "polls",
    "polls": "polls",
    "poll_memory": "polls",
    "poll_memory.json": "polls",
    "뉴스": "news",
    "뉴스 메모리": "news",
    "뉴스메모리": "news",
    "최신소식": "news",
    "최신 소식": "news",
    "소식": "news",
    "news": "news",
    "daily_news": "news",
    "news_memory": "news",
    "news_memory.json": "news",
}


def get_memory_section_file(section: str):
    return MEMORY_FILE.with_name(MEMORY_SECTION_FILES[section])


def resolve_memory_section(raw_text: str) -> str | None:
    text = raw_text.strip().casefold()
    return MEMORY_SECTION_ALIASES.get(text)


def _normalize_lookup_text(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def find_user_records_by_nickname(nickname: str) -> list[tuple[int, dict]]:
    lookup = _normalize_lookup_text(nickname)
    if not lookup:
        return []

    matches = []
    for user_id_text, user_data in load_memory().items():
        if not user_id_text.isdigit() or not isinstance(user_data, dict):
            continue
        if _normalize_lookup_text(user_data.get("nickname")) == lookup:
            matches.append((int(user_id_text), dict(user_data)))
    return matches


def find_nickname_conflicts(nickname: str, *, exclude_user_id: int | None = None) -> list[tuple[int, dict]]:
    return [
        (user_id, user_data)
        for user_id, user_data in find_user_records_by_nickname(nickname)
        if exclude_user_id is None or user_id != exclude_user_id
    ]


def format_memory_section_list() -> str:
    return "\n".join(
        f"- {MEMORY_SECTION_LABELS[section]}: `{filename}`"
        for section, filename in MEMORY_SECTION_FILES.items()
    )


def _read_json_file_unlocked(path) -> dict:
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_file_unlocked(path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = path.with_name(f"{path.name}.tmp")
    temp_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_file.replace(path)


def _section_file_exists(section: str) -> bool:
    return get_memory_section_file(section).exists()


def _split_legacy_memory(legacy_data: dict) -> dict:
    return {
        section: _extract_memory_section(legacy_data, section)
        for section in MEMORY_SECTION_FILES
    }


def _combine_memory_sections(sections: dict[str, dict]) -> dict:
    data = dict(sections.get("conversation", {}))
    for section, data_key in MEMORY_SECTION_DATA_KEYS.items():
        section_data = sections.get(section, {})
        if section_data:
            data[data_key] = section_data
    return data


def _read_memory_unlocked() -> dict:
    legacy_sections = _split_legacy_memory(_read_json_file_unlocked(MEMORY_FILE))
    sections = {}
    for section in MEMORY_SECTION_FILES:
        sections[section] = (
            _read_json_file_unlocked(get_memory_section_file(section))
            if _section_file_exists(section)
            else legacy_sections[section]
        )
    return _combine_memory_sections(sections)


def _write_memory_unlocked(data: dict) -> None:
    for section in MEMORY_SECTION_FILES:
        _write_json_file_unlocked(
            get_memory_section_file(section),
            _extract_memory_section(data, section),
        )


def _extract_memory_section(data: dict, section: str) -> dict:
    if section == "conversation":
        return {
            key: value
            for key, value in data.items()
            if key.isdigit() and isinstance(value, dict)
        }
    data_key = MEMORY_SECTION_DATA_KEYS.get(section)
    if data_key is not None and isinstance(data.get(data_key), dict):
        return data[data_key]
    return {}


def ensure_memory_section_file(section: str):
    with _MEMORY_LOCK:
        path = get_memory_section_file(section)
        if not path.exists():
            _write_json_file_unlocked(path, _extract_memory_section(_read_memory_unlocked(), section))
        return path


def reset_memory_section(section: str) -> None:
    with _MEMORY_LOCK:
        _write_json_file_unlocked(get_memory_section_file(section), {})


def load_memory() -> dict:
    with _MEMORY_LOCK:
        return _read_memory_unlocked()


def save_memory(data: dict) -> None:
    with _MEMORY_LOCK:
        _write_memory_unlocked(data)


def update_memory(mutator):
    with _MEMORY_LOCK:
        data = _read_memory_unlocked()
        result = mutator(data)
        _write_memory_unlocked(data)
        return result


def _new_room_data() -> dict:
    return {
        "internet_mode": False,
        "group_mode": False,
        "history": [],
    }


def _normalize_room_data(room_data: dict) -> dict:
    room_data.setdefault("internet_mode", False)
    room_data.setdefault("group_mode", False)
    room_data.setdefault("history", [])
    return room_data


def _new_user_data(user_id: int, display_name: str) -> dict:
    affection = 1004 if user_id == SPECIAL_USER_ID else DEFAULT_AFFECTION
    name = SPECIAL_USER_NAME if user_id == SPECIAL_USER_ID else display_name
    nickname = SPECIAL_USER_NICKNAME if user_id == SPECIAL_USER_ID else "개척자"

    return {
        "name": name,
        "nickname": nickname,
        "affection": affection,
        "last_seen": None,
        "history": [],
    }


def _normalize_user_data(user_id: int, display_name: str, user_data: dict) -> dict:
    user_data.setdefault("last_seen", None)
    user_data.setdefault("history", [])

    if user_id == SPECIAL_USER_ID:
        user_data["name"] = SPECIAL_USER_NAME
        user_data["affection"] = 1004
        user_data["nickname"] = SPECIAL_USER_NICKNAME
    elif user_data.get("name") != display_name:
        user_data["name"] = display_name

    return user_data


def get_room_key(message: discord.Message) -> str:
    guild_id = message.guild.id if message.guild else 0
    channel_id = message.channel.id
    return f"{guild_id}:{channel_id}"


def get_room_data(room_key: str) -> dict:
    def mutate(all_data: dict) -> dict:
        rooms = all_data.setdefault(ROOMS_KEY, {})
        room_data = rooms.setdefault(room_key, _new_room_data())
        return _normalize_room_data(room_data)

    return update_memory(mutate)


def get_existing_room_data(room_key: str) -> dict | None:
    all_data = load_memory()
    room_data = all_data.get(ROOMS_KEY, {}).get(room_key)
    if not isinstance(room_data, dict):
        return None
    return _normalize_room_data(room_data)


def update_room_data(room_key: str, room_data: dict) -> None:
    def mutate(all_data: dict) -> None:
        all_data.setdefault(ROOMS_KEY, {})[room_key] = _normalize_room_data(room_data)

    update_memory(mutate)


def add_room_history(
    room_data: dict,
    speaker_name: str,
    role: str,
    content: str,
    user_id: int | None = None,
    nickname: str | None = None,
    affection: int | None = None,
) -> dict:
    history = room_data.get("history", [])
    history.append({
        "speaker": speaker_name,
        "role": role,
        "content": content,
        "user_id": user_id,
        "nickname": nickname,
        "affection": affection,
    })
    room_data["history"] = history[-MAX_ROOM_HISTORY:]
    return room_data


def get_user_data(user_id: int, display_name: str) -> dict:
    key = str(user_id)

    def mutate(all_data: dict) -> dict:
        user_data = all_data.setdefault(key, _new_user_data(user_id, display_name))
        return _normalize_user_data(user_id, display_name, user_data)

    return update_memory(mutate)


def update_user_data(user_id: int, user_data: dict) -> None:
    def mutate(all_data: dict) -> None:
        display_name = str(user_data.get("name", "알 수 없음"))
        all_data[str(user_id)] = _normalize_user_data(user_id, display_name, user_data)

    update_memory(mutate)


def add_history(user_data: dict, role: str, content: str, **extra) -> dict:
    history = user_data.get("history", [])
    entry = {
        "role": role,
        "content": content,
    }
    entry.update(extra)
    history.append(entry)
    user_data["history"] = history[-MAX_HISTORY:]
    return user_data


def record_room_user_message(
    message: discord.Message,
    room_key: str,
    room_data: dict,
    content: str | None = None,
) -> bool:
    display_name = getattr(message.author, "display_name", message.author.name)
    user_data = get_user_data(message.author.id, display_name)
    user_data["last_seen"] = get_current_time_text()
    update_user_data(message.author.id, user_data)
    if content is None:
        content = clean_discord_content(message)

    if not content.strip():
        return False

    room_data = get_room_data(room_key)
    room_data = add_room_history(
        room_data,
        speaker_name=display_name,
        role="user",
        content=content,
        user_id=message.author.id,
        nickname=user_data.get("nickname"),
        affection=user_data.get("affection"),
    )
    update_room_data(room_key, room_data)
    return True


def record_room_bot_message(room_key: str, room_data: dict, content: str) -> None:
    room_data = add_room_history(
        room_data,
        speaker_name=BOT_DISPLAY_NAME,
        role="assistant",
        content=content,
    )
    update_room_data(room_key, room_data)
