from dataclasses import dataclass
import re

import discord

from .config import SPECIAL_USER_ID
from .storage import (
    find_nickname_conflicts,
    find_user_records_by_nickname,
    get_user_data,
    update_user_data,
)

DISCORD_USER_ID_PATTERN = re.compile(r"^(?:<@!?(\d{15,25})>|@?(\d{15,25}))\s+(.+)$")
QUOTED_TARGET_PATTERN = re.compile(r"^[\"'`“”‘’]([^\"'`“”‘’]+)[\"'`“”‘’]\s+(.+)$")


@dataclass(frozen=True)
class _NicknameTarget:
    user_id: int
    display_name: str
    mention: str | None = None
    user_data: dict | None = None


def _target_mentions(
    message: discord.Message,
    client_user: discord.ClientUser | discord.User | None,
) -> list[discord.User | discord.Member]:
    if client_user is None:
        return list(getattr(message, "mentions", []) or [])
    return [
        member
        for member in getattr(message, "mentions", []) or []
        if getattr(member, "id", None) != client_user.id
    ]


def _format_user_record(user_id: int, user_data: dict) -> str:
    name = str(user_data.get("name") or "알 수 없음")
    nickname = str(user_data.get("nickname") or "없음")
    return f"{name}/호칭 `{nickname}` (`{user_id}`)"


def _format_user_record_list(records: list[tuple[int, dict]], *, limit: int = 5) -> str:
    lines = [_format_user_record(user_id, user_data) for user_id, user_data in records[:limit]]
    if len(records) > limit:
        lines.append(f"외 {len(records) - limit}명")
    return ", ".join(lines)


def _nickname_conflict_message(nickname: str, target_user_id: int) -> str | None:
    conflicts = find_nickname_conflicts(nickname, exclude_user_id=target_user_id)
    if not conflicts:
        return None
    return (
        f"…`{nickname}` 호칭은 이미 {_format_user_record_list(conflicts)}이(가) 쓰고 있어. "
        "호칭으로 대상을 찾을 때 헷갈리지 않게 다른 호칭을 써줘."
    )


def _guild_member_by_id(message: discord.Message, user_id: int) -> discord.Member | None:
    guild = getattr(message, "guild", None)
    get_member = getattr(guild, "get_member", None)
    if get_member is None:
        return None
    return get_member(user_id)


def _nickname_target_from_user(user: discord.User | discord.Member) -> _NicknameTarget:
    display_name = getattr(user, "display_name", getattr(user, "name", str(user.id)))
    return _NicknameTarget(
        user_id=user.id,
        display_name=display_name,
        mention=getattr(user, "mention", None),
        user_data=get_user_data(user.id, display_name),
    )


async def _resolve_nickname_target_by_id(
    message: discord.Message,
    client: discord.Client,
    user_id: int,
) -> _NicknameTarget:
    member = _guild_member_by_id(message, user_id)
    if member is not None:
        return _nickname_target_from_user(member)

    user = None
    get_user = getattr(client, "get_user", None)
    if get_user is not None:
        user = get_user(user_id)

    if user is None:
        fetch_user = getattr(client, "fetch_user", None)
        if fetch_user is not None:
            try:
                user = await fetch_user(user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                user = None

    if user is not None:
        return _nickname_target_from_user(user)

    user_data = get_user_data(user_id, str(user_id))
    return _NicknameTarget(
        user_id=user_id,
        display_name=str(user_data.get("name") or user_id),
        user_data=user_data,
    )


def _resolve_nickname_target_by_nickname(
    message: discord.Message,
    nickname: str,
) -> tuple[_NicknameTarget | None, str | None]:
    matches = find_user_records_by_nickname(nickname)
    if not matches:
        return None, "…그 호칭으로 저장된 유저를 찾지 못했어. 멘션, 디스코드 ID, 또는 이미 저장된 고유 호칭으로 적어줘."
    if len(matches) > 1:
        return (
            None,
            f"…`{nickname}` 호칭을 쓰는 사람이 {len(matches)}명이라 누구인지 모르겠어. "
            f"멘션이나 디스코드 ID로 다시 적어줘: {_format_user_record_list(matches)}",
        )

    user_id, user_data = matches[0]
    member = _guild_member_by_id(message, user_id)
    if member is not None:
        return _nickname_target_from_user(member), None

    return (
        _NicknameTarget(
            user_id=user_id,
            display_name=str(user_data.get("name") or nickname),
            mention=None,
            user_data=user_data,
        ),
        None,
    )


def _target_text_forms(target: _NicknameTarget) -> list[str]:
    forms = [
        target.mention,
        f"@{target.display_name}",
        target.display_name,
        str(target.user_id),
    ]
    if target.user_data:
        name = target.user_data.get("name")
        if name:
            forms.extend([str(name), f"@{name}"])

    deduped = []
    seen = set()
    for form in forms:
        if not form:
            continue
        key = str(form).casefold()
        if key in seen:
            continue
        deduped.append(str(form))
        seen.add(key)
    return sorted(deduped, key=len, reverse=True)


def _strip_target_prefix(argument_text: str, target: _NicknameTarget) -> str:
    for form in _target_text_forms(target):
        match = re.match(rf"\s*{re.escape(form)}(?:\s+|$)", argument_text, re.IGNORECASE)
        if match:
            return argument_text[match.end():].strip()
    return argument_text.strip()


def _split_target_and_nickname(argument_text: str) -> tuple[str | None, str | None]:
    quoted_match = QUOTED_TARGET_PATTERN.match(argument_text.strip())
    if quoted_match:
        return quoted_match.group(1).strip(), quoted_match.group(2).strip()

    parts = argument_text.strip().split(maxsplit=1)
    if len(parts) != 2:
        return None, None
    return parts[0].strip(), parts[1].strip()


async def handle_nickname_command(
    *,
    message: discord.Message,
    argument_text: str,
    user_data: dict,
    client: discord.Client,
    special_user: bool,
) -> None:
    argument_text = argument_text.strip()
    if not argument_text:
        await message.channel.send("…호칭을 비워둘 수는 없어.")
        return

    if not special_user:
        new_nickname = argument_text
        conflict_message = _nickname_conflict_message(new_nickname, message.author.id)
        if conflict_message:
            await message.channel.send(conflict_message)
            return

        user_data["nickname"] = new_nickname
        update_user_data(message.author.id, user_data)
        await message.channel.send(f"응. 이제부터는 {new_nickname}(이)라고 불러볼게.")
        return

    target = None
    new_nickname = None
    target_mentions = _target_mentions(message, getattr(client, "user", None))
    if target_mentions:
        target = _nickname_target_from_user(target_mentions[0])
        new_nickname = _strip_target_prefix(argument_text, target)
    else:
        id_match = DISCORD_USER_ID_PATTERN.match(argument_text)
        if id_match:
            user_id = int(id_match.group(1) or id_match.group(2))
            target = await _resolve_nickname_target_by_id(message, client, user_id)
            new_nickname = id_match.group(3).strip()
        else:
            target_text, parsed_nickname = _split_target_and_nickname(argument_text)
            if target_text and parsed_nickname:
                target, error_message = _resolve_nickname_target_by_nickname(message, target_text)
                if error_message:
                    await message.channel.send(error_message)
                    return
                new_nickname = parsed_nickname

    if target is None:
        await message.channel.send("…너는 특별한 호칭이 이미 정해져 있어서 바꿀 수 없어. 다른 사람은 `/호칭 @유저 새호칭`처럼 대상을 같이 적어줘.")
        return

    if target.user_id == SPECIAL_USER_ID:
        await message.channel.send("…특별 사용자의 호칭은 고정이라 바꿀 수 없어.")
        return

    new_nickname = (new_nickname or "").strip()
    if not new_nickname:
        await message.channel.send("…새 호칭을 같이 적어줘. 예: `/호칭 @유저 이카`")
        return

    conflict_message = _nickname_conflict_message(new_nickname, target.user_id)
    if conflict_message:
        await message.channel.send(conflict_message)
        return

    target_data = dict(target.user_data or get_user_data(target.user_id, target.display_name))
    target_data["nickname"] = new_nickname
    update_user_data(target.user_id, target_data)
    await message.channel.send(f"…응. {target.display_name}의 호칭을 `{new_nickname}`로 바꿨어.")
