from dataclasses import dataclass
import re

import discord

from .storage import find_nickname_conflicts, find_user_records_by_nickname, get_user_data, load_memory

USER_ID_PREFIX_PATTERN = re.compile(r"^\s*(?:<@!?(\d{15,25})>|@?(\d{15,25}))(?:\s+(.+))?$")
QUOTED_TARGET_PATTERN = re.compile(r"^\s*[\"'`“”‘’]([^\"'`“”‘’]+)[\"'`“”‘’](?:\s+(.+))?$")


@dataclass(frozen=True)
class UserCommandTarget:
    user_id: int
    display_name: str
    mention: str | None = None
    user_data: dict | None = None


def target_mentions(
    message: discord.Message,
    client_user: discord.ClientUser | discord.User | None,
) -> list[discord.User | discord.Member]:
    mentions = list(getattr(message, "mentions", []) or [])
    if client_user is None:
        return mentions
    return [member for member in mentions if getattr(member, "id", None) != client_user.id]


def format_user_record(user_id: int, user_data: dict) -> str:
    name = str(user_data.get("name") or "알 수 없음")
    nickname = str(user_data.get("nickname") or "없음")
    return f"{name}/호칭 `{nickname}` (`{user_id}`)"


def format_user_record_list(records: list[tuple[int, dict]], *, limit: int = 5) -> str:
    lines = [format_user_record(user_id, user_data) for user_id, user_data in records[:limit]]
    if len(records) > limit:
        lines.append(f"외 {len(records) - limit}명")
    return ", ".join(lines)


def nickname_conflict_message(nickname: str, target_user_id: int) -> str | None:
    conflicts = find_nickname_conflicts(nickname, exclude_user_id=target_user_id)
    if not conflicts:
        return None
    return (
        f"…`{nickname}` 호칭은 이미 {format_user_record_list(conflicts)}이(가) 쓰고 있어. "
        "호칭으로 대상을 찾을 때 헷갈리지 않게 다른 호칭을 써줘."
    )


def guild_member_by_id(message: discord.Message, user_id: int) -> discord.Member | None:
    guild = getattr(message, "guild", None)
    get_member = getattr(guild, "get_member", None)
    if get_member is None:
        return None
    return get_member(user_id)


def user_target_from_user(user: discord.User | discord.Member) -> UserCommandTarget:
    display_name = getattr(user, "display_name", getattr(user, "name", str(user.id)))
    return UserCommandTarget(
        user_id=user.id,
        display_name=display_name,
        mention=getattr(user, "mention", None),
        user_data=get_user_data(user.id, display_name),
    )


def _user_target_from_stored_data(user_id: int, user_data: dict) -> UserCommandTarget:
    return UserCommandTarget(
        user_id=user_id,
        display_name=str(user_data.get("name") or user_id),
        mention=None,
        user_data=user_data,
    )


async def resolve_user_target_by_id(
    message: discord.Message,
    client: discord.Client,
    user_id: int,
) -> tuple[UserCommandTarget | None, str | None]:
    if user_id <= 0:
        return None, "…사용자 ID가 올바르지 않아."

    member = guild_member_by_id(message, user_id)
    if member is not None:
        return user_target_from_user(member), None

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
        return user_target_from_user(user), None

    stored_data = load_memory().get(str(user_id))
    if isinstance(stored_data, dict):
        return _user_target_from_stored_data(user_id, stored_data), None

    return None, "…그 사용자 ID를 찾지 못했어. 멘션, 유효한 디스코드 ID, 또는 저장된 고유 호칭으로 적어줘."


def resolve_user_target_by_nickname(
    message: discord.Message,
    nickname: str,
) -> tuple[UserCommandTarget | None, str | None]:
    matches = find_user_records_by_nickname(nickname)
    if not matches:
        return None, "…그 호칭으로 저장된 유저를 찾지 못했어. 멘션, 디스코드 ID, 또는 이미 저장된 고유 호칭으로 적어줘."
    if len(matches) > 1:
        return (
            None,
            f"…`{nickname}` 호칭을 쓰는 사람이 {len(matches)}명이라 누구인지 모르겠어. "
            f"멘션이나 디스코드 ID로 다시 적어줘: {format_user_record_list(matches)}",
        )

    user_id, user_data = matches[0]
    member = guild_member_by_id(message, user_id)
    if member is not None:
        return user_target_from_user(member), None

    return _user_target_from_stored_data(user_id, user_data), None


def target_text_forms(target: UserCommandTarget) -> list[str]:
    forms = [
        target.mention,
        f"@{target.display_name}",
        target.display_name,
        str(target.user_id),
    ]
    if target.user_data:
        name = target.user_data.get("name")
        nickname = target.user_data.get("nickname")
        if name:
            forms.extend([str(name), f"@{name}"])
        if nickname:
            forms.append(str(nickname))

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


def strip_target_prefix(argument_text: str, target: UserCommandTarget) -> str:
    for form in target_text_forms(target):
        match = re.match(rf"\s*{re.escape(form)}(?:\s+|$)", argument_text, re.IGNORECASE)
        if match:
            return argument_text[match.end():].strip()
    return argument_text.strip()


def split_quoted_or_first_token(argument_text: str) -> tuple[str | None, str]:
    quoted_match = QUOTED_TARGET_PATTERN.match(argument_text.strip())
    if quoted_match:
        return quoted_match.group(1).strip(), (quoted_match.group(2) or "").strip()

    parts = argument_text.strip().split(maxsplit=1)
    if not parts:
        return None, ""
    return parts[0].strip(), parts[1].strip() if len(parts) > 1 else ""


async def resolve_explicit_user_target(
    *,
    message: discord.Message,
    client: discord.Client,
    argument_text: str,
) -> tuple[UserCommandTarget | None, str, str | None]:
    argument_text = argument_text.strip()
    if not argument_text:
        return None, "", "…대상 사용자를 먼저 적어줘. 멘션, 디스코드 ID, 또는 저장된 고유 호칭이 필요해."

    mentions = target_mentions(message, getattr(client, "user", None))
    if mentions:
        target = user_target_from_user(mentions[0])
        return target, strip_target_prefix(argument_text, target), None

    id_match = USER_ID_PREFIX_PATTERN.match(argument_text)
    if id_match:
        user_id = int(id_match.group(1) or id_match.group(2))
        target, error_message = await resolve_user_target_by_id(message, client, user_id)
        return target, (id_match.group(3) or "").strip(), error_message

    target_text, remainder = split_quoted_or_first_token(argument_text)
    if not target_text:
        return None, "", "…대상 사용자를 먼저 적어줘. 멘션, 디스코드 ID, 또는 저장된 고유 호칭이 필요해."

    target, error_message = resolve_user_target_by_nickname(message, target_text)
    return target, remainder, error_message
