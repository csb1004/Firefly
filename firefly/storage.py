import json
from threading import RLock

import discord

from .config import (
    BOT_DISPLAY_NAME,
    DEFAULT_AFFECTION,
    MAX_HISTORY,
    MAX_ROOM_HISTORY,
    MEMORY_FILE,
    ROOMS_KEY,
    SPECIAL_USER_ID,
    SPECIAL_USER_NAME,
    SPECIAL_USER_NICKNAME,
)
from .text_utils import clean_discord_content, get_current_time_text

_MEMORY_LOCK = RLock()


def _read_memory_unlocked() -> dict:
    if not MEMORY_FILE.exists():
        return {}

    try:
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_memory_unlocked(data: dict) -> None:
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = MEMORY_FILE.with_name(f"{MEMORY_FILE.name}.tmp")
    temp_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_file.replace(MEMORY_FILE)


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
