import discord

from .affection import change_user_affection, set_user_affection
from .ai import generate_reply, summarize_conversation
from .config import DEFAULT_AFFECTION, MEMORY_FILE, SPECIAL_USER_ID, SUMMARY_DEFAULT_LIMIT
from .embeds import (
    create_help_embed,
    create_room_history_embed,
    create_special_help_embed,
    create_summary_embed,
    create_user_info_embed,
)
from .polls import cancel_poll_tasks, close_poll_from_command, create_poll_from_command
from .storage import get_user_data, save_memory, update_room_data, update_user_data
from .text_utils import parse_last_int_arg


def is_special_user(user_id: int) -> bool:
    return user_id == SPECIAL_USER_ID


def matches_command(user_text: str, command: str) -> bool:
    return user_text == command or user_text.startswith(f"{command} ")


SPECIAL_ONLY_COMMAND_PREFIXES = (
    "/메모리파일",
    "/메모리초기화",
    "/메모리파일초기화",
    "/유저정보",
    "/호감도설정",
    "/호감도증감",
    "/투표마감",
    "/투표",
    "/인터넷모드",
    "/단체모드",
    "/방기억",
    "/방초기화",
    "/방상태",
)


def is_special_only_command(user_text: str) -> bool:
    return any(matches_command(user_text, command) for command in SPECIAL_ONLY_COMMAND_PREFIXES)


def get_target_mentions(
    message: discord.Message,
    client_user: discord.ClientUser | discord.User | None,
) -> list[discord.User | discord.Member]:
    if client_user is None:
        return list(message.mentions)
    return [member for member in message.mentions if member.id != client_user.id]


def _parse_summary_args(user_text: str, room_data: dict) -> tuple[str, int]:
    args = user_text.replace("/요약", "", 1).strip().split()
    scope = "room" if room_data.get("group_mode") else "user"
    limit = SUMMARY_DEFAULT_LIMIT

    for token in args:
        normalized = token.lower()
        if normalized in {"방", "단체", "채널", "room", "channel"}:
            scope = "room"
        elif normalized in {"개인", "나", "dm", "user"}:
            scope = "user"
        elif normalized.isdigit():
            limit = max(1, min(80, int(normalized)))

    return scope, limit


async def _send_summary(
    message: discord.Message,
    user_text: str,
    user_data: dict,
    room_data: dict,
) -> None:
    scope, limit = _parse_summary_args(user_text, room_data)
    author_name = getattr(message.author, "display_name", message.author.name)

    if scope == "room":
        entries = room_data.get("history", [])
        channel_name = getattr(message.channel, "name", "DM")
        scope_name = f"디스코드 방 #{channel_name}"
        title = "최근 방 대화 요약"
    else:
        entries = user_data.get("history", [])
        scope_name = f"{author_name}와 반디의 개인 대화"
        title = "최근 개인 대화 요약"

    async with message.channel.typing():
        summary, used_count = await summarize_conversation(entries, scope_name, limit)
        await message.channel.send(embed=create_summary_embed(title, summary, used_count))


async def handle_mentioned_message(
    message: discord.Message,
    user_text: str,
    user_data: dict,
    room_key: str,
    room_data: dict,
    client: discord.Client,
) -> None:
    author_id = message.author.id
    special_user = is_special_user(author_id)

    if special_user and user_text == "/메모리파일":
        if not MEMORY_FILE.exists():
            await message.channel.send("…아직 저장된 메모리 파일이 없어.")
            return
        await message.channel.send(file=discord.File(str(MEMORY_FILE)))
        return

    memory_reset_command = next(
        (
            command
            for command in ("/메모리초기화", "/메모리파일초기화")
            if matches_command(user_text, command)
        ),
        None,
    )
    if memory_reset_command:
        if not special_user:
            await message.channel.send("…메모리 초기화는 특별 사용자만 사용할 수 있어.")
            return

        confirm_text = user_text.replace(memory_reset_command, "", 1).strip()
        if confirm_text != "확인":
            await message.channel.send(
                "…메모리 파일 전체를 비우려면 `/메모리초기화 확인`이라고 다시 입력해줘. "
                "개인 기억, 방 기억, 투표 예약이 모두 초기화돼."
            )
            return

        save_memory({})
        cancel_poll_tasks()
        await message.channel.send("…응. 메모리 파일을 빈 상태로 초기화했어.")
        return

    if special_user and user_text.startswith("/유저정보"):
        target_mentions = get_target_mentions(message, client.user)

        if not target_mentions:
            await message.channel.send("…확인할 대상을 멘션해줘. 예: /유저정보 @개척자")
            return

        target_user = target_mentions[0]
        display_name = getattr(target_user, "display_name", target_user.name)
        target_data = get_user_data(target_user.id, display_name)

        await message.channel.send(embed=create_user_info_embed(target_user, target_data))
        return

    if special_user and user_text.startswith("/호감도설정 "):
        target_mentions = get_target_mentions(message, client.user)

        if not target_mentions:
            await message.channel.send("…대상을 먼저 멘션해줘. 예: /호감도설정 @유저 75")
            return

        if len(user_text.split()) < 3:
            await message.channel.send("…숫자도 같이 적어줘. 예: /호감도설정 @유저 75")
            return

        value = parse_last_int_arg(user_text)
        if value is None:
            await message.channel.send("…호감도는 숫자로 적어줘.")
            return

        target_user = target_mentions[0]
        new_value = set_user_affection(target_user.id, value)

        if target_user.id == SPECIAL_USER_ID:
            await message.channel.send("…내 호감도는 건드릴 수 없어. 이미 1004로 고정이야.")
        else:
            target_name = getattr(target_user, "display_name", target_user.name)
            await message.channel.send(f"…{target_name}의 호감도를 {new_value}로 맞춰뒀어.")
        return

    if special_user and user_text.startswith("/호감도증감 "):
        target_mentions = get_target_mentions(message, client.user)

        if not target_mentions:
            await message.channel.send("…대상을 먼저 멘션해줘. 예: /호감도증감 @유저 -10")
            return

        if len(user_text.split()) < 3:
            await message.channel.send("…증감할 숫자도 같이 적어줘. 예: /호감도증감 @유저 5")
            return

        delta = parse_last_int_arg(user_text)
        if delta is None:
            await message.channel.send("…증감값은 숫자로 적어줘.")
            return

        target_user = target_mentions[0]
        new_value = change_user_affection(target_user.id, delta)

        if target_user.id == SPECIAL_USER_ID:
            await message.channel.send("…내 호감도는 그대로 1004야.")
        else:
            sign = "+" if delta >= 0 else ""
            target_name = getattr(target_user, "display_name", target_user.name)
            await message.channel.send(
                f"…{target_name}의 호감도를 {sign}{delta}만큼 조정했어. 지금은 {new_value}야."
            )
        return

    if user_text == "/호감도":
        if special_user:
            await message.channel.send("…너에 대한 마음은 굳이 세면 1004쯤 될 거야.")
        else:
            await message.channel.send(
                f"…지금 {user_data.get('nickname', user_data.get('name', '너'))}에 대한 마음은 "
                f"{user_data.get('affection', DEFAULT_AFFECTION)}/100 정도야."
            )
        return

    if user_text == "/초기화":
        user_data["history"] = []
        update_user_data(author_id, user_data)
        await message.channel.send("…응. 최근 대화는 비워뒀어.")
        return

    if user_text.startswith("/호칭 "):
        new_nickname = user_text.replace("/호칭 ", "", 1).strip()
        if not new_nickname:
            await message.channel.send("…호칭을 비워둘 수는 없어.")
            return
        if special_user:
            await message.channel.send("…너는 특별한 호칭이 이미 정해져 있어서 바꿀 수 없어.")
            return

        user_data["nickname"] = new_nickname
        update_user_data(author_id, user_data)
        await message.channel.send(f"응. 이제부터는 {new_nickname}(이)라고 불러볼게.")
        return

    if matches_command(user_text, "/투표"):
        if not special_user:
            await message.channel.send("…투표 기능은 특별 사용자만 사용할 수 있어.")
            return

        await create_poll_from_command(message, user_text, client)
        return

    if matches_command(user_text, "/투표마감"):
        if not special_user:
            await message.channel.send("…투표 마감은 특별 사용자만 사용할 수 있어.")
            return

        await close_poll_from_command(message, client)
        return

    if user_text == "/요약" or user_text.startswith("/요약 "):
        await _send_summary(message, user_text, user_data, room_data)
        return

    if special_user and user_text.startswith("/인터넷모드 "):
        value = user_text.replace("/인터넷모드 ", "", 1).strip().lower()

        if value not in {"on", "off"}:
            await message.channel.send("…on 또는 off로 적어줘.")
            return

        room_data["internet_mode"] = value == "on"
        update_room_data(room_key, room_data)
        await message.channel.send(f"…이 방의 인터넷 검색 모드를 {'켰어' if value == 'on' else '껐어'}.")
        return

    if special_user and user_text.startswith("/단체모드 "):
        value = user_text.replace("/단체모드 ", "", 1).strip().lower()

        if value not in {"on", "off"}:
            await message.channel.send("…on 또는 off로 적어줘.")
            return

        if value == "on":
            room_data["group_mode"] = True
            room_data["history"] = []
            update_room_data(room_key, room_data)
            await message.channel.send("…이 방의 단체 모드를 켰어. 지금부터의 대화만 기억할게.")
        else:
            room_data["group_mode"] = False
            update_room_data(room_key, room_data)
            await message.channel.send("…이 방의 단체 모드를 껐어.")
        return

    if special_user and user_text == "/방기억":
        await message.channel.send(embed=create_room_history_embed(message, room_data))
        return

    if special_user and user_text == "/방초기화":
        room_data["history"] = []
        update_room_data(room_key, room_data)
        await message.channel.send("…이 방의 단체 기억을 비워뒀어.")
        return

    if special_user and user_text == "/방상태":
        await message.channel.send(
            f"…이 방 설정이야.\n"
            f"- 인터넷 검색 모드: {'on' if room_data.get('internet_mode') else 'off'}\n"
            f"- 단체 모드: {'on' if room_data.get('group_mode') else 'off'}\n"
            f"- 저장된 방 대화 수: {len(room_data.get('history', []))}"
        )
        return

    if user_text == "/도움말":
        embed = create_special_help_embed() if special_user else create_help_embed()
        await message.channel.send(embed=embed)
        return

    if user_text.startswith("/") and not special_user and is_special_only_command(user_text):
        await message.channel.send("…그 명령어는 특별 사용자만 사용할 수 있어.")
        return

    if user_text.startswith("/"):
        await message.channel.send("그 명령어는 잘 모르겠어. '/도움말'을 불러서 사용 가능한 명령어들을 확인해봐.")
        return

    async with message.channel.typing():
        display_name = getattr(message.author, "display_name", message.author.name)
        reply = await generate_reply(
            user_message=user_text,
            user_id=author_id,
            display_name=display_name,
            room_key=room_key,
        )
        await message.channel.send(reply[:1900])
