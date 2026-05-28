import re
from dataclasses import dataclass

import discord


ROLE_USAGE_TEXT = (
    "역할 명령 사용법이야.\n"
    "- `/역할 부여 @유저 @역할`\n"
    "- `/역할 제거 @유저 @역할`\n"
    "- `/역할 색 @역할 #ffaa00`\n"
    "- `/역할 이름 @역할 새이름`\n"
    "- `/역할 권한추가 @역할 메시지관리 역할관리`\n"
    "- `/역할 권한제거 @역할 관리자 멘션`\n"
    "역할 이름을 직접 쓸 수도 있지만, 이름이 비슷하면 역할 멘션이 가장 안전해."
)

ACTION_ASSIGN = "assign"
ACTION_REMOVE = "remove"
ACTION_COLOR = "color"
ACTION_RENAME = "rename"
ACTION_ALLOW_PERMISSIONS = "allow_permissions"
ACTION_DENY_PERMISSIONS = "deny_permissions"
ACTION_HELP = "help"

ASSIGN_WORDS = ("부여", "지급", "달아", "달기", "줘", "주기", "추가")
REMOVE_WORDS = ("제거", "해제", "빼", "빼기", "박탈", "삭제")
COLOR_WORDS = ("색", "색상", "컬러", "color")
RENAME_WORDS = ("이름", "명칭", "rename", "name")
PERMISSION_WORDS = ("권한", "permission", "permissions")
ALLOW_PERMISSION_WORDS = ("추가", "부여", "허용", "켜", "넣어", "allow", "enable", "add")
DENY_PERMISSION_WORDS = ("제거", "해제", "빼", "빼기", "꺼", "삭제", "deny", "disable", "remove")

PERMISSION_ALIASES = {
    "관리자": "administrator",
    "어드민": "administrator",
    "administrator": "administrator",
    "admin": "administrator",
    "채널관리": "manage_channels",
    "채널 관리": "manage_channels",
    "manage_channels": "manage_channels",
    "서버관리": "manage_guild",
    "서버 관리": "manage_guild",
    "manage_guild": "manage_guild",
    "역할관리": "manage_roles",
    "역할 관리": "manage_roles",
    "manage_roles": "manage_roles",
    "메시지관리": "manage_messages",
    "메시지 관리": "manage_messages",
    "메시지삭제": "manage_messages",
    "manage_messages": "manage_messages",
    "멘션": "mention_everyone",
    "전체멘션": "mention_everyone",
    "mention_everyone": "mention_everyone",
    "닉네임관리": "manage_nicknames",
    "닉네임 관리": "manage_nicknames",
    "manage_nicknames": "manage_nicknames",
    "킥": "kick_members",
    "추방": "kick_members",
    "kick_members": "kick_members",
    "밴": "ban_members",
    "차단": "ban_members",
    "ban_members": "ban_members",
    "초대": "create_instant_invite",
    "초대생성": "create_instant_invite",
    "create_instant_invite": "create_instant_invite",
    "메시지보내기": "send_messages",
    "메시지 보내기": "send_messages",
    "send_messages": "send_messages",
    "채널보기": "view_channel",
    "채널 보기": "view_channel",
    "메시지보기": "view_channel",
    "view_channel": "view_channel",
    "첨부파일": "attach_files",
    "파일첨부": "attach_files",
    "attach_files": "attach_files",
    "링크첨부": "embed_links",
    "embed_links": "embed_links",
    "반응추가": "add_reactions",
    "add_reactions": "add_reactions",
    "스레드관리": "manage_threads",
    "스레드 관리": "manage_threads",
    "manage_threads": "manage_threads",
    "웹훅관리": "manage_webhooks",
    "웹훅 관리": "manage_webhooks",
    "manage_webhooks": "manage_webhooks",
}

COLOR_ALIASES = {
    "빨강": 0xED4245,
    "빨간색": 0xED4245,
    "주황": 0xF47B20,
    "노랑": 0xFEE75C,
    "초록": 0x57F287,
    "파랑": 0x3498DB,
    "보라": 0x9B59B6,
    "분홍": 0xEB459E,
    "검정": 0x23272A,
    "하양": 0xFFFFFF,
}


@dataclass(frozen=True)
class RoleRequest:
    action: str
    role: discord.Role | None = None
    member: discord.Member | None = None
    color_value: int | None = None
    new_name: str | None = None
    permission_flags: tuple[str, ...] = ()


def _normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    folded = text.casefold()
    return any(word.casefold() in folded for word in words)


def _role_mentions(message: discord.Message) -> list[discord.Role]:
    return list(getattr(message, "role_mentions", []) or [])


def _mentioned_member(message: discord.Message) -> discord.Member | discord.User | None:
    mentions = list(getattr(message, "mentions", []) or [])
    return mentions[0] if mentions else None


def _guild_roles(guild: discord.Guild) -> list[discord.Role]:
    return list(getattr(guild, "roles", []) or [])


def _resolve_member(message: discord.Message, text: str) -> discord.Member | discord.User | None:
    member = _mentioned_member(message)
    if member is not None:
        return member

    guild = message.guild
    id_match = re.search(r"<@!?(\d{15,25})>|\b(\d{15,25})\b", text)
    if not id_match:
        return None

    member_id = int(id_match.group(1) or id_match.group(2))
    get_member = getattr(guild, "get_member", None)
    if get_member is None:
        return None
    return get_member(member_id)


def _resolve_role(message: discord.Message, text: str) -> discord.Role | None:
    mentions = _role_mentions(message)
    if mentions:
        return mentions[0]

    guild = message.guild
    role_id_match = re.search(r"<@&(\d{15,25})>", text)
    if role_id_match:
        get_role = getattr(guild, "get_role", None)
        if get_role is not None:
            role = get_role(int(role_id_match.group(1)))
            if role is not None:
                return role

    role_id = None
    for match in re.finditer(r"\b(\d{15,25})\b", text):
        candidate = int(match.group(1))
        if re.search(rf"<@!?{candidate}>", text):
            continue
        role_id = candidate
        break

    if role_id is not None:
        get_role = getattr(guild, "get_role", None)
        if get_role is not None:
            role = get_role(role_id)
            if role is not None:
                return role

    folded_text = text.casefold()
    candidates = sorted(
        (
            role
            for role in _guild_roles(guild)
            if getattr(role, "name", "").casefold() in folded_text
            and not getattr(role, "is_default", lambda: False)()
        ),
        key=lambda role: len(getattr(role, "name", "")),
        reverse=True,
    )
    return candidates[0] if candidates else None


def _parse_action(text: str) -> str:
    if not text or text.casefold() in {"도움말", "help"}:
        return ACTION_HELP

    if _contains_any(text, PERMISSION_WORDS):
        if _contains_any(text, DENY_PERMISSION_WORDS):
            return ACTION_DENY_PERMISSIONS
        if _contains_any(text, ALLOW_PERMISSION_WORDS):
            return ACTION_ALLOW_PERMISSIONS
        return ACTION_HELP

    if _contains_any(text, COLOR_WORDS):
        return ACTION_COLOR
    if _contains_any(text, RENAME_WORDS):
        return ACTION_RENAME
    if _contains_any(text, REMOVE_WORDS):
        return ACTION_REMOVE
    if _contains_any(text, ASSIGN_WORDS):
        return ACTION_ASSIGN
    return ACTION_HELP


def _parse_color_value(text: str) -> int | None:
    hex_match = re.search(r"#?([0-9a-fA-F]{6})\b", text)
    if hex_match:
        return int(hex_match.group(1), 16)

    folded = text.casefold()
    for name, value in COLOR_ALIASES.items():
        if name.casefold() in folded:
            return value
    return None


def _remove_fragment(text: str, fragment: str) -> str:
    if not fragment:
        return text
    return re.sub(re.escape(fragment), " ", text, count=1, flags=re.IGNORECASE)


def _extract_new_name(text: str, role: discord.Role | None) -> str | None:
    patterns = (
        r"(?:이름|명칭)(?:을|를)?\s+(.+?)(?:으로|로|이라고|라고)?\s*(?:바꿔|변경|설정|수정)",
        r"(?:rename|name)\s+(.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _normalize_spaces(match.group(1)).strip("\"'`")

    remaining = text
    if role is not None:
        remaining = _remove_fragment(remaining, getattr(role, "mention", ""))
        remaining = _remove_fragment(remaining, getattr(role, "name", ""))

    for word in ("역할", "이름", "명칭", "rename", "name", "바꿔줘", "바꿔", "변경해줘", "변경", "설정해줘", "설정"):
        remaining = _remove_fragment(remaining, word)
    remaining = _normalize_spaces(remaining).strip("\"'`")
    return remaining or None


def _valid_permission_flags() -> set[str]:
    valid_flags = getattr(discord.Permissions, "VALID_FLAGS", {})
    if isinstance(valid_flags, dict):
        return set(valid_flags.keys())
    return set(valid_flags)


def _permission_alias_key(text: str) -> str:
    return re.sub(r"[\s,_-]+", "", text.casefold())


def _extract_permission_flags(text: str) -> tuple[str, ...]:
    valid_flags = _valid_permission_flags()
    folded_compact = _permission_alias_key(text)
    flags = []

    for alias, flag in PERMISSION_ALIASES.items():
        if flag in valid_flags and _permission_alias_key(alias) in folded_compact:
            flags.append(flag)

    for token in re.split(r"[\s,|/]+", text):
        token = token.strip("`'\".,;:()[]{}")
        if not token:
            continue
        normalized = token.casefold()
        flag = PERMISSION_ALIASES.get(token) or PERMISSION_ALIASES.get(normalized)
        if flag is None and normalized in valid_flags:
            flag = normalized
        if flag in valid_flags:
            flags.append(flag)

    return tuple(dict.fromkeys(flags))


def _permission_text_without_role(text: str, role: discord.Role | None) -> str:
    remaining = text
    if role is not None:
        remaining = _remove_fragment(remaining, getattr(role, "mention", ""))
        remaining = _remove_fragment(remaining, getattr(role, "name", ""))

    for word in (
        "권한추가",
        "권한제거",
        "permission",
        "permissions",
        "권한",
    ):
        remaining = _remove_fragment(remaining, word)
    return remaining


def _request_from_text(message: discord.Message, text: str) -> RoleRequest:
    text = _normalize_spaces(text)
    action = _parse_action(text)
    if action == ACTION_HELP:
        return RoleRequest(action=ACTION_HELP)

    role = _resolve_role(message, text)
    member = _resolve_member(message, text)

    if action == ACTION_COLOR:
        return RoleRequest(action=action, role=role, color_value=_parse_color_value(text))
    if action == ACTION_RENAME:
        return RoleRequest(action=action, role=role, new_name=_extract_new_name(text, role))
    if action in {ACTION_ALLOW_PERMISSIONS, ACTION_DENY_PERMISSIONS}:
        return RoleRequest(
            action=action,
            role=role,
            permission_flags=_extract_permission_flags(_permission_text_without_role(text, role)),
        )
    return RoleRequest(action=action, role=role, member=member)


def is_role_command_text(user_text: str) -> bool:
    text = _normalize_spaces(user_text)
    if text.startswith("/역할") or text.startswith("/role"):
        return True
    return "역할" in text and _parse_action(text) != ACTION_HELP


def _format_role(role: discord.Role) -> str:
    return getattr(role, "mention", None) or f"`{getattr(role, 'name', '알 수 없는 역할')}`"


def _format_member(member: discord.Member | discord.User) -> str:
    return getattr(member, "mention", None) or f"`{getattr(member, 'display_name', getattr(member, 'name', '알 수 없는 유저'))}`"


def _missing_target_message(request: RoleRequest) -> str | None:
    if request.action in {ACTION_ASSIGN, ACTION_REMOVE}:
        if request.member is None:
            return "…역할을 줄/뺄 유저를 멘션해줘."
        if request.role is None:
            return "…대상 역할을 멘션하거나 정확한 역할 이름을 적어줘."
    elif request.role is None:
        return "…대상 역할을 멘션하거나 정확한 역할 이름을 적어줘."

    if request.action == ACTION_COLOR and request.color_value is None:
        return "…색은 `#ffaa00` 같은 6자리 HEX나 빨강/파랑 같은 이름으로 적어줘."
    if request.action == ACTION_RENAME and not request.new_name:
        return "…새 역할 이름을 같이 적어줘."
    if request.action in {ACTION_ALLOW_PERMISSIONS, ACTION_DENY_PERMISSIONS} and not request.permission_flags:
        return "…바꿀 권한 이름을 같이 적어줘. 예: 관리자, 메시지관리, 역할관리, 멘션"
    return None


async def _edit_role_permissions(
    role: discord.Role,
    flags: tuple[str, ...],
    value: bool,
    reason: str,
) -> None:
    permissions = discord.Permissions(getattr(role.permissions, "value", 0))
    for flag in flags:
        setattr(permissions, flag, value)
    await role.edit(permissions=permissions, reason=reason)


async def handle_role_command(message: discord.Message, raw_text: str) -> None:
    if message.guild is None:
        await message.channel.send("…역할 관리는 서버 안에서만 할 수 있어.")
        return

    request = _request_from_text(message, raw_text)
    if request.action == ACTION_HELP:
        await message.channel.send(ROLE_USAGE_TEXT)
        return

    missing_message = _missing_target_message(request)
    if missing_message:
        await message.channel.send(missing_message)
        return

    reason = f"Firefly role command by {getattr(message.author, 'id', 'unknown')}"

    try:
        if request.action == ACTION_ASSIGN:
            await request.member.add_roles(request.role, reason=reason)
            await message.channel.send(f"…응. {_format_member(request.member)}에게 {_format_role(request.role)} 역할을 부여했어.")
        elif request.action == ACTION_REMOVE:
            await request.member.remove_roles(request.role, reason=reason)
            await message.channel.send(f"…응. {_format_member(request.member)}에게서 {_format_role(request.role)} 역할을 제거했어.")
        elif request.action == ACTION_COLOR:
            await request.role.edit(color=discord.Color(request.color_value), reason=reason)
            await message.channel.send(f"…응. {_format_role(request.role)} 색을 `#{request.color_value:06X}`로 바꿨어.")
        elif request.action == ACTION_RENAME:
            old_name = getattr(request.role, "name", "역할")
            await request.role.edit(name=request.new_name, reason=reason)
            await message.channel.send(f"…응. `{old_name}` 역할 이름을 `{request.new_name}`로 바꿨어.")
        elif request.action in {ACTION_ALLOW_PERMISSIONS, ACTION_DENY_PERMISSIONS}:
            enabled = request.action == ACTION_ALLOW_PERMISSIONS
            await _edit_role_permissions(request.role, request.permission_flags, enabled, reason)
            action_text = "추가" if enabled else "제거"
            await message.channel.send(
                f"…응. {_format_role(request.role)} 역할에서 `{', '.join(request.permission_flags)}` 권한을 {action_text}했어."
            )
    except discord.Forbidden:
        await message.channel.send("…디스코드 권한이나 역할 순서 때문에 처리하지 못했어. 봇 역할이 대상 역할보다 위에 있는지 확인해줘.")
    except discord.HTTPException as exc:
        await message.channel.send(f"…디스코드가 역할 변경을 거절했어. ({exc.status})")
