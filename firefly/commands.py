import discord

from .affection import change_user_affection, set_user_affection
from .admin_status import build_admin_status_text
from .ai import generate_reply, summarize_conversation, summarize_voice_recording, summarize_voice_search
from .command_registry import ADMIN_STATUS_COMMAND, VOICE_SEARCH_COMMAND, matched_alias
from .commands_parser import (
    SPECIAL_ONLY_COMMAND_PREFIXES,
    SUMMARY_SCOPE_TOKENS,
    command_arg,
    is_special_only_command,
    matches_command,
    parse_summary_args,
    summary_recording_filename,
)
from .config import DEFAULT_AFFECTION, MEMORY_FILE, SPECIAL_USER_ID, SUMMARY_DEFAULT_LIMIT
from .embeds import (
    create_help_embed,
    create_room_history_embed,
    create_special_help_embed,
    create_summary_embed,
    create_user_info_embed,
)
from .news import (
    cancel_daily_news_task,
    handle_news_command,
    is_news_command_text,
    start_daily_news_task,
)
from .polls import cancel_poll_tasks, close_poll_from_command, create_poll_from_command
from .storage import get_user_data, load_memory, save_memory, update_room_data, update_user_data
from .text_utils import parse_last_int_arg
from .voice_search import load_voice_search_selection, parse_voice_search_args
from .voice import start_voice_recording, stop_voice_recording
from .voice_records import (
    VoiceRecordNotFound,
    format_recording_list,
    get_recording_path,
    list_recordings,
    read_transcript_entries,
)


def is_special_user(user_id: int) -> bool:
    return user_id == SPECIAL_USER_ID


def get_target_mentions(
    message: discord.Message,
    client_user: discord.ClientUser | discord.User | None,
) -> list[discord.User | discord.Member]:
    if client_user is None:
        return list(message.mentions)
    return [member for member in message.mentions if member.id != client_user.id]


def _parse_summary_args(user_text: str, room_data: dict) -> tuple[str, int]:
    return parse_summary_args(user_text, room_data)


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


def _command_arg(user_text: str, command: str) -> str:
    return command_arg(user_text, command)


def _summary_recording_filename(user_text: str) -> str | None:
    return summary_recording_filename(user_text)


LATEST_RECORDING_TOKENS = {"최근", "마지막", "latest", "last"}


def _resolve_recording_summary_filename(filename: str) -> str | None:
    if filename.strip().lower() not in LATEST_RECORDING_TOKENS:
        return filename

    records = list_recordings()
    if not records:
        return None
    return str(records[0].get("filename") or "") or None


def _extract_auto_command(reply: str) -> str | None:
    lines = [line.strip() for line in reply.strip().splitlines() if line.strip()]
    if len(lines) != 1:
        return None

    command = lines[0]
    if not command.startswith("/") or command == "/":
        return None
    return command[:1900]


async def _run_auto_command_from_reply(
    *,
    reply: str,
    message: discord.Message,
    user_data: dict,
    room_key: str,
    room_data: dict,
    client: discord.Client,
) -> bool:
    auto_command = _extract_auto_command(reply)
    if not auto_command:
        return False

    await handle_mentioned_message(
        message=message,
        user_text=auto_command,
        user_data=user_data,
        room_key=room_key,
        room_data=room_data,
        client=client,
    )
    return True


async def _send_recording_list(message: discord.Message) -> None:
    records = list_recordings()
    await message.channel.send(format_recording_list(records))


async def _send_recording_summary(message: discord.Message, filename: str) -> None:
    try:
        entries = read_transcript_entries(filename)
    except VoiceRecordNotFound:
        await message.channel.send("…그 이름의 통화 기록 파일을 찾지 못했어. `/대화목록`으로 파일명을 확인해줘.")
        return

    async with message.channel.typing():
        summary, used_count = await summarize_voice_recording(entries, filename)
        await message.channel.send(
            embed=create_summary_embed(f"통화 기록 요약: {filename}", summary, used_count)
        )

async def _send_voice_search(message: discord.Message, raw_text: str) -> None:
    request = parse_voice_search_args(raw_text)
    if not request.query:
        await message.channel.send("사용법: `/기록검색 [파일명] 찾고 싶은 말이나 질문`")
        return

    try:
        selection = load_voice_search_selection(request)
    except VoiceRecordNotFound:
        await message.channel.send("검색할 수 있는 통화 기록을 찾지 못했어. 통화 기록 목록에서 파일명을 먼저 확인해줘.")
        return

    async with message.channel.typing():
        summary, used_count = await summarize_voice_search(
            selection.entries,
            selection.filename,
            request.query,
            matched_count=selection.matched_count,
        )
        await message.channel.send(
            embed=create_summary_embed(f"통화 기록 검색: {selection.filename}", summary, used_count)
        )


async def _send_admin_status(message: discord.Message, room_key: str, room_data: dict) -> None:
    guild_id = message.guild.id if message.guild else None
    status_text = build_admin_status_text(
        load_memory(),
        current_room_key=room_key,
        current_room_data=room_data,
        guild_id=guild_id,
    )
    await message.channel.send(f"```text\n{status_text}\n```")


async def _send_memory_or_recording_file(message: discord.Message, filename: str | None = None) -> None:
    if not filename:
        if not MEMORY_FILE.exists():
            await message.channel.send("…아직 저장된 메모리 파일이 없어.")
            return
        await message.channel.send(file=discord.File(str(MEMORY_FILE)))
        return

    try:
        path = get_recording_path(filename)
    except VoiceRecordNotFound:
        await message.channel.send("…그 이름의 통화 기록 파일을 찾지 못했어. `/대화목록`으로 파일명을 확인해줘.")
        return

    await message.channel.send(file=discord.File(str(path), filename=path.name))


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

    voice_search_alias = matched_alias(user_text, VOICE_SEARCH_COMMAND.aliases)
    if voice_search_alias:
        if not special_user:
            await message.channel.send("그 명령어는 특별 사용자만 사용할 수 있어.")
            return
        await _send_voice_search(message, _command_arg(user_text, voice_search_alias))
        return

    admin_status_alias = matched_alias(user_text, ADMIN_STATUS_COMMAND.aliases)
    if admin_status_alias:
        if not special_user:
            await message.channel.send("그 명령어는 특별 사용자만 사용할 수 있어.")
            return
        await _send_admin_status(message, room_key, room_data)
        return

    if is_news_command_text(user_text):
        await handle_news_command(message, user_text, client)
        return

    if matches_command(user_text, "/기록"):
        if not special_user:
            await message.channel.send("…통화 기록은 특별 사용자만 사용할 수 있어.")
            return

        _, response_text, _ = await start_voice_recording(
            client,
            user=message.author,
            text_channel=message.channel,
        )
        await message.channel.send(response_text)
        return

    if matches_command(user_text, "/기록중지"):
        if not special_user:
            await message.channel.send("…통화 기록은 특별 사용자만 사용할 수 있어.")
            return

        if message.guild is None:
            await message.channel.send("…서버 안에서만 기록을 멈출 수 있어.")
            return

        _, response_text, _ = await stop_voice_recording(message.guild.id)
        await message.channel.send(response_text)
        return

    if matches_command(user_text, "/대화목록"):
        if not special_user:
            await message.channel.send("…통화 기록 목록은 특별 사용자만 볼 수 있어.")
            return
        await _send_recording_list(message)
        return

    if special_user and matches_command(user_text, "/메모리파일"):
        filename = _command_arg(user_text, "/메모리파일") or None
        await _send_memory_or_recording_file(message, filename)
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
        cancel_daily_news_task()
        start_daily_news_task(client)
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
        recording_filename = _summary_recording_filename(user_text)
        if recording_filename:
            if not special_user:
                await message.channel.send("…통화 기록 요약은 특별 사용자만 사용할 수 있어.")
                return
            resolved_filename = _resolve_recording_summary_filename(recording_filename)
            if not resolved_filename:
                await message.channel.send("…요약할 통화 기록이 없어. 먼저 `/대화목록`으로 확인해줘.")
                return
            await _send_recording_summary(message, resolved_filename)
            return

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

    if await _run_auto_command_from_reply(
        reply=reply,
        message=message,
        user_data=user_data,
        room_key=room_key,
        room_data=room_data,
        client=client,
    ):
        return

    await message.channel.send(reply[:1900])
