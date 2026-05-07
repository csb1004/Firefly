import json

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
from .text_utils import get_current_time_text


def load_memory() -> dict:
    if not MEMORY_FILE.exists():
        return {}

    try:
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_memory(data: dict) -> None:
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_room_key(message: discord.Message) -> str:
    guild_id = message.guild.id if message.guild else 0
    channel_id = message.channel.id
    return f"{guild_id}:{channel_id}"


def get_room_data(room_key: str) -> dict:
    all_data = load_memory()
    rooms = all_data.setdefault(ROOMS_KEY, {})

    if room_key not in rooms:
        rooms[room_key] = {
            "internet_mode": False,
            "group_mode": False,
            "history": [],
        }
        save_memory(all_data)

    room_data = rooms[room_key]
    room_data.setdefault("internet_mode", False)
    room_data.setdefault("group_mode", False)
    room_data.setdefault("history", [])
    return room_data


def update_room_data(room_key: str, room_data: dict) -> None:
    all_data = load_memory()
    all_data.setdefault(ROOMS_KEY, {})[room_key] = room_data
    save_memory(all_data)


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
    all_data = load_memory()
    key = str(user_id)

    if key not in all_data:
        affection = 1004 if user_id == SPECIAL_USER_ID else DEFAULT_AFFECTION
        name = SPECIAL_USER_NAME if user_id == SPECIAL_USER_ID else display_name
        nickname = SPECIAL_USER_NICKNAME if user_id == SPECIAL_USER_ID else "개척자"

        all_data[key] = {
            "name": name,
            "nickname": nickname,
            "affection": affection,
            "last_seen": None,
            "history": [],
        }
        save_memory(all_data)

    user_data = all_data[key]
    user_data.setdefault("last_seen", None)
    user_data.setdefault("history", [])

    if user_id == SPECIAL_USER_ID:
        user_data["name"] = SPECIAL_USER_NAME
        user_data["affection"] = 1004
        user_data["nickname"] = SPECIAL_USER_NICKNAME
    elif user_data.get("name") != display_name:
        user_data["name"] = display_name

    all_data[key] = user_data
    save_memory(all_data)
    return user_data


def update_user_data(user_id: int, user_data: dict) -> None:
    all_data = load_memory()

    if user_id == SPECIAL_USER_ID:
        user_data["affection"] = 1004

    all_data[str(user_id)] = user_data
    save_memory(all_data)


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


def record_room_user_message(message: discord.Message, room_key: str, room_data: dict) -> None:
    display_name = getattr(message.author, "display_name", message.author.name)
    user_data = get_user_data(message.author.id, display_name)
    user_data["last_seen"] = get_current_time_text()
    update_user_data(message.author.id, user_data)

    room_data = add_room_history(
        room_data,
        speaker_name=display_name,
        role="user",
        content=message.content,
        user_id=message.author.id,
        nickname=user_data.get("nickname"),
        affection=user_data.get("affection"),
    )
    update_room_data(room_key, room_data)


def record_room_bot_message(room_key: str, room_data: dict, content: str) -> None:
    room_data = add_room_history(
        room_data,
        speaker_name=BOT_DISPLAY_NAME,
        role="assistant",
        content=content,
    )
    update_room_data(room_key, room_data)
