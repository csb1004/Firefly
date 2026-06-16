from collections import deque
from dataclasses import dataclass
from types import SimpleNamespace

import discord

from .affection import change_user_affection, set_user_affection
from .admin_status import build_admin_status_text
from .ai import (
    generate_reply,
    generate_silent_auto_command,
    plan_state_updates,
    plan_tool_use,
    summarize_conversation,
    summarize_voice_recording,
    summarize_voice_search,
)
from .brain import (
    LONG_TERM_MEMORY_KEY,
    SHORT_TERM_MEMORY_KEY,
    add_brain_note,
    delete_brain_memory,
    format_brain_notes,
    parse_brain_delete_target,
    parse_brain_index_and_note,
    update_brain_note,
)
from .command_registry import ADMIN_STATUS_COMMAND, ROLE_COMMAND, VOICE_SEARCH_COMMAND, matched_alias
from .commands_parser import (
    SPECIAL_ONLY_COMMAND_PREFIXES,
    SUMMARY_SCOPE_TOKENS,
    command_arg,
    is_special_only_command,
    matches_command,
    parse_summary_args,
    summary_recording_filename,
)
from .config import BOT_DISPLAY_NAME, DEFAULT_AFFECTION, SPECIAL_USER_ID, SPECIAL_USER_NAME, SUMMARY_DEFAULT_LIMIT
from .embeds import (
    create_help_embed,
    create_profile_embed,
    create_room_history_embed,
    create_special_help_embed,
    create_summary_embed,
    create_user_info_embed,
)
from .news import handle_news_command, is_news_command_text
from .polls import cancel_poll_tasks, close_poll_from_command, create_poll_from_command
from .reasoning import format_reasoning_status, reasoning_effort_label, set_room_reasoning_effort
from .role_commands import handle_role_command
from .storage import (
    MEMORY_SECTION_LABELS,
    add_history,
    add_room_history,
    ensure_memory_section_file,
    format_memory_section_list,
    get_memory_section_file,
    get_room_data,
    get_user_data,
    load_memory,
    reset_memory_section,
    resolve_memory_section,
    update_room_data,
    update_user_data,
)
from .state_updates import (
    filter_hidden_state_update_commands,
    has_hidden_affection_update,
    is_state_update_command,
)
from .text_utils import clamp_text, get_current_time_text, parse_last_int_arg
from .tool_planner import PLAN_CHAT, PLAN_CLARIFY, PLAN_COMMAND, PLAN_COMMAND_THEN_REPLY, PLAN_REJECT, ToolPlan
from .user_targets import resolve_explicit_user_target, target_mentions
from .utility_commands import (
    CommandAdapterRequest,
    CommandUsageError,
    MAX_ADAPTER_COMMANDS,
    format_dice_result,
    format_team_split_result,
    parse_command_adapter_args,
    parse_dice_args,
    parse_team_split_args,
    roll_dice,
    split_members_into_teams,
)
from .nickname_commands import handle_nickname_command
from .voice_search import load_voice_search_selection, parse_voice_search_args
from .voice import start_voice_recording, stop_voice_recording
from .voice_records import (
    VoiceRecordNotFound,
    format_recording_list,
    get_recording_path,
    list_recordings,
    read_transcript_entries,
    resolve_recording_reference,
)


def is_special_user(user_id: int) -> bool:
    return user_id == SPECIAL_USER_ID


def get_target_mentions(
    message: discord.Message,
    client_user: discord.ClientUser | discord.User | None,
) -> list[discord.User | discord.Member]:
    return target_mentions(message, client_user)


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
ADAPTER_COMMAND_OUTPUT_LIMIT = 1200
ADAPTER_CONTEXT_LIMIT = 3500
AUTO_COMMAND_HISTORY_OUTPUT_LIMIT = 1200
MAX_MEMORY_FILE_SEND_BYTES = 24 * 1024 * 1024
PERMISSION_DENIED_MESSAGE = "…그 명령어를 사용할 권한이 없어."
MEMORY_FILE_COMMAND_ALIASES = (
    "/메모리파일",
    "/메모리 파일",
    "/memoryfile",
    "메모리파일",
    "메모리 파일",
    "memoryfile",
)
ADAPTER_CHAIN_LIMIT_MESSAGE = (
    f"…연속 실행은 한 번에 최대 {MAX_ADAPTER_COMMANDS}개까지만 할게. "
    "중간 결과를 보고 이어서 다시 부탁해줘."
)
ADAPTER_BLOCKED_COMMAND_PREFIXES = (
    "/실행",
    "/명령답변",
    "/검색실행",
    "/인터넷실행",
    "/검색답변",
    "/인터넷모드",
    "/초기화",
    "/메모리초기화",
    "/메모리파일초기화",
    "/방초기화",
    "/역할",
    "/role",
)
SILENT_GROUP_MEMORY_COMMAND_PREFIXES = ("/뇌추가", "/뇌삭제", "/호감도증감")


def _resolve_recording_summary_filename(filename: str) -> str | None:
    if filename.strip().lower() not in LATEST_RECORDING_TOKENS:
        try:
            return resolve_recording_reference(filename, records=list_recordings())
        except VoiceRecordNotFound:
            return filename

    records = list_recordings()
    if not records:
        return None
    return str(records[0].get("filename") or "") or None


class _NoopTyping:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def _embed_to_text(embed: discord.Embed) -> str:
    parts = []
    if embed.title:
        parts.append(str(embed.title))
    if embed.description:
        parts.append(str(embed.description))
    for field in embed.fields:
        parts.append(f"{field.name}: {field.value}")
    return "\n".join(parts).strip()


def _send_payload_to_text(args: tuple, kwargs: dict) -> str:
    parts = []
    if args and args[0] is not None:
        parts.append(str(args[0]))
    content = kwargs.get("content")
    if content:
        parts.append(str(content))

    embed = kwargs.get("embed")
    if embed is not None:
        embed_text = _embed_to_text(embed)
        if embed_text:
            parts.append(embed_text)

    for item in kwargs.get("embeds") or []:
        embed_text = _embed_to_text(item)
        if embed_text:
            parts.append(embed_text)

    file = kwargs.get("file")
    if file is not None:
        parts.append(f"파일: {getattr(file, 'filename', '첨부 파일')}")

    files = kwargs.get("files") or []
    for item in files:
        parts.append(f"파일: {getattr(item, 'filename', '첨부 파일')}")

    return "\n".join(part for part in parts if part).strip()


class _CommandCaptureChannel:
    def __init__(self, channel, *, forward: bool = True):
        self._channel = channel
        self._forward = forward
        self.outputs: list[str] = []

    def typing(self):
        typing = getattr(self._channel, "typing", None)
        if typing is None:
            return _NoopTyping()
        return typing()

    async def send(self, *args, **kwargs):
        output = _send_payload_to_text(args, kwargs)
        if output:
            self.outputs.append(output)
        if self._forward:
            return await self._channel.send(*args, **kwargs)
        return None

    def __getattr__(self, name: str):
        return getattr(self._channel, name)


class _CommandCaptureMessage:
    def __init__(
        self,
        original: discord.Message,
        channel: _CommandCaptureChannel,
        *,
        author=None,
        mentions=None,
    ):
        self.author = author or original.author
        self.channel = channel
        self.guild = original.guild
        self.mentions = getattr(original, "mentions", []) if mentions is None else mentions
        self.role_mentions = getattr(original, "role_mentions", [])
        self.reference = getattr(original, "reference", None)
        self.content = getattr(original, "content", "")


def _adapter_command_allowed(command_text: str) -> bool:
    return not any(
        command_text == prefix or command_text.startswith(f"{prefix} ")
        for prefix in ADAPTER_BLOCKED_COMMAND_PREFIXES
    )


def _matches_any_command_prefix(command_text: str, prefixes: tuple[str, ...]) -> bool:
    return any(matches_command(command_text, prefix) for prefix in prefixes)


def _split_state_update_commands(commands: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    state_updates = []
    visible_commands = []
    for command in commands:
        if is_state_update_command(command):
            state_updates.append(command)
        else:
            visible_commands.append(command)
    return tuple(state_updates), tuple(visible_commands)


@dataclass(frozen=True)
class _StateUpdateExecutionResult:
    ran: bool = False
    affection_updated: bool = False


def _adapter_blocked_message(command_text: str) -> str:
    if command_text == "/인터넷모드" or command_text.startswith("/인터넷모드 "):
        return "…`/실행` 안에서는 `/인터넷모드` 대신 `/검색실행`을 써줘. 그 답변 한 번에만 인터넷 검색을 사용할게."
    return "…그 명령어는 `/실행` 안에서 실행하지 않게 막아뒀어."


def _format_adapter_command_summary(index: int, command_text: str, command_output: str) -> str:
    return (
        f"[{index}] 명령어: {command_text}\n"
        f"결과:\n{command_output[:ADAPTER_COMMAND_OUTPUT_LIMIT]}"
    )


def _format_adapter_context(command_summaries: list[str]) -> str | None:
    if not command_summaries:
        return None
    return "\n\n".join(command_summaries)[:ADAPTER_CONTEXT_LIMIT]


def _parse_memory_reset_args(raw_text: str) -> tuple[str | None, str]:
    target_text, separator, confirm_text = raw_text.rpartition(" ")
    if not separator:
        return None, confirm_text.strip()
    return resolve_memory_section(target_text), confirm_text.strip()


def _extract_auto_command(reply: str) -> str | None:
    lines = [line.strip() for line in reply.strip().splitlines() if line.strip()]
    if len(lines) != 1:
        return None

    command = lines[0]
    if not command.startswith("/") or command == "/":
        return None
    return command[:1900]


def _format_auto_command_history(command_text: str, command_output: str) -> str:
    output = command_output or "명령어가 실행됐지만 표시된 결과 메시지는 없었어."
    clipped_output = clamp_text(output, AUTO_COMMAND_HISTORY_OUTPUT_LIMIT, "\n...")
    return (
        "자동 명령 실행 기록: "
        f"사용자 요청을 `{command_text}` 명령으로 처리했어.\n"
        f"결과:\n{clipped_output}"
    )


def _record_auto_command_context(
    *,
    message: discord.Message,
    user_text: str,
    room_key: str,
    command_text: str,
    command_output: str,
) -> None:
    display_name = getattr(message.author, "display_name", message.author.name)
    user_data = get_user_data(message.author.id, display_name)
    summary = _format_auto_command_history(command_text, command_output)

    user_data = add_history(user_data, "user", user_text)
    user_data = add_history(user_data, "assistant", summary)
    user_data["last_seen"] = get_current_time_text()
    update_user_data(message.author.id, user_data)

    room_data = get_room_data(room_key)
    room_data = add_room_history(
        room_data,
        speaker_name=display_name,
        role="user",
        content=user_text,
        user_id=message.author.id,
        nickname=user_data.get("nickname"),
        affection=user_data.get("affection"),
    )
    room_data = add_room_history(
        room_data,
        speaker_name=BOT_DISPLAY_NAME,
        role="assistant",
        content=summary,
    )
    update_room_data(room_key, room_data)


async def _run_auto_command_from_reply(
    *,
    reply: str,
    message: discord.Message,
    user_text: str,
    user_data: dict,
    room_key: str,
    room_data: dict,
    client: discord.Client,
    allowed_prefixes: tuple[str, ...] | None = None,
    record_context: bool = True,
    forward_output: bool = True,
) -> bool:
    auto_command = _extract_auto_command(reply)
    if not auto_command:
        return False
    if allowed_prefixes is not None and not _matches_any_command_prefix(auto_command, allowed_prefixes):
        return False

    capture_channel = _CommandCaptureChannel(message.channel, forward=forward_output)
    capture_message = _CommandCaptureMessage(message, capture_channel)
    await handle_mentioned_message(
        message=capture_message,
        user_text=auto_command,
        user_data=user_data,
        room_key=room_key,
        room_data=room_data,
        client=client,
    )
    if record_context:
        command_output = "\n".join(capture_channel.outputs).strip()
        _record_auto_command_context(
            message=message,
            user_text=user_text,
            room_key=room_key,
            command_text=auto_command,
            command_output=command_output,
        )
    return True


def _state_update_author():
    return SimpleNamespace(
        id=SPECIAL_USER_ID,
        name=SPECIAL_USER_NAME,
        display_name=SPECIAL_USER_NAME,
        mention=f"<@{SPECIAL_USER_ID}>",
    )


async def _run_silent_state_update_commands(
    *,
    commands: tuple[str, ...],
    message: discord.Message,
    room_key: str,
    room_data: dict,
    client: discord.Client,
) -> _StateUpdateExecutionResult:
    runnable_commands = filter_hidden_state_update_commands(
        commands,
        user_id=message.author.id,
    )
    if not runnable_commands:
        return _StateUpdateExecutionResult()

    capture_channel = _CommandCaptureChannel(message.channel, forward=False)
    capture_message = _CommandCaptureMessage(
        message,
        capture_channel,
        author=_state_update_author(),
        mentions=[],
    )
    state_user_data = get_user_data(SPECIAL_USER_ID, SPECIAL_USER_NAME)
    for command_text in runnable_commands:
        await handle_mentioned_message(
            message=capture_message,
            user_text=command_text,
            user_data=state_user_data,
            room_key=room_key,
            room_data=room_data,
            client=client,
        )
    return _StateUpdateExecutionResult(
        ran=True,
        affection_updated=has_hidden_affection_update(runnable_commands, user_id=message.author.id),
    )


async def handle_silent_group_memory_update(
    *,
    message: discord.Message,
    user_text: str,
    user_data: dict,
    room_key: str,
    room_data: dict,
    client: discord.Client,
) -> bool:
    if not is_special_user(message.author.id):
        return False

    display_name = getattr(message.author, "display_name", message.author.name)
    reply = await generate_silent_auto_command(
        user_message=user_text,
        user_id=message.author.id,
        display_name=display_name,
        room_key=room_key,
        allowed_command_prefixes=SILENT_GROUP_MEMORY_COMMAND_PREFIXES,
    )
    if not reply:
        return False

    return await _run_auto_command_from_reply(
        reply=reply,
        message=message,
        user_text=user_text,
        user_data=user_data,
        room_key=room_key,
        room_data=room_data,
        client=client,
        allowed_prefixes=SILENT_GROUP_MEMORY_COMMAND_PREFIXES,
        record_context=False,
        forward_output=False,
    )


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


async def _brain_target_data(
    message: discord.Message,
    client: discord.Client,
    raw_text: str,
) -> tuple[object | None, dict | None, str, str | None]:
    return await _resolve_target_argument(message, client, raw_text)


async def _send_brain_notes(
    message: discord.Message,
    client: discord.Client,
    raw_text: str,
) -> None:
    target, target_data, _, error_message = await _brain_target_data(message, client, raw_text)
    if error_message or target is None or target_data is None:
        await message.channel.send(error_message or "…대상 사용자를 찾지 못했어.")
        return

    await message.channel.send(
        f"`{target.display_name}`에 대한 반디의 기억이야.\n"
        f"```text\n{format_brain_notes(target_data)}\n```"
    )


async def _add_brain_note(
    message: discord.Message,
    client: discord.Client,
    raw_text: str,
) -> None:
    target, target_data, note, error_message = await _brain_target_data(message, client, raw_text)
    if error_message or target is None or target_data is None:
        await message.channel.send(error_message or "…대상 사용자를 찾지 못했어.")
        return
    if not note:
        await message.channel.send(
            "…대상과 저장할 기억 후보를 같이 적어줘. "
            "예: `/뇌추가 @유저 쉽게 불안해하지만 끝까지 확인하려고 한다`"
        )
        return

    try:
        result = add_brain_note(target_data, note)
    except ValueError as exc:
        await message.channel.send(f"…{exc}")
        return
    update_user_data(target.user_id, target_data)
    if result.status == "ignored":
        await message.channel.send(
            f"…응. `{target.display_name}`에 대한 현재 관계 맥락으로 받아들였어."
        )
    elif result.status == "promoted":
        await message.channel.send(
            f"…응. `{target.display_name}`에 대한 기억 후보를 장기 기억 {result.index}번으로 승격했어."
        )
    elif result.status == "merged_long_term":
        await message.channel.send(
            f"…응. `{target.display_name}`에 대한 기존 장기 기억 {result.index}번의 반복성을 갱신했어."
        )
    else:
        await message.channel.send(
            f"…응. `{target.display_name}`에 대한 단기 기억 후보 S{result.index}번으로 보관했어."
        )


async def _update_brain_note(
    message: discord.Message,
    client: discord.Client,
    raw_text: str,
) -> None:
    target, target_data, args, error_message = await _brain_target_data(message, client, raw_text)
    if error_message or target is None or target_data is None:
        await message.channel.send(error_message or "…대상 사용자를 찾지 못했어.")
        return
    index, note = parse_brain_index_and_note(args)
    if index is None or not note:
        await message.channel.send("…대상, 수정할 번호, 새 내용을 같이 적어줘. 예: `/뇌수정 @유저 1 신중하지만 결정을 미루지는 않는다`")
        return
    if not update_brain_note(target_data, index, note):
        await message.channel.send("…그 번호의 평가를 찾지 못했어.")
        return

    update_user_data(target.user_id, target_data)
    await message.channel.send(f"…응. `{target.display_name}`에 대한 {index}번 평가를 고쳤어.")


async def _delete_brain_note(
    message: discord.Message,
    client: discord.Client,
    raw_text: str,
) -> None:
    target, target_data, args, error_message = await _brain_target_data(message, client, raw_text)
    if error_message or target is None or target_data is None:
        await message.channel.send(error_message or "…대상 사용자를 찾지 못했어.")
        return
    delete_target = parse_brain_delete_target(args)
    if delete_target is None:
        await message.channel.send("…대상과 삭제할 기억 번호를 적어줘. 예: `/뇌삭제 @유저 1`, `/뇌삭제 @유저 S1`")
        return

    result = delete_brain_memory(target_data, delete_target)
    if result is None:
        await message.channel.send("…그 번호의 기억을 찾지 못했어.")
        return

    update_user_data(target.user_id, target_data)
    if result.memory_type == SHORT_TERM_MEMORY_KEY and result.index is None:
        await message.channel.send(
            f"…응. `{target.display_name}`에 대한 단기 기억 후보 {len(result.contents)}개를 지웠어."
        )
    elif result.memory_type == SHORT_TERM_MEMORY_KEY:
        await message.channel.send(
            f"…응. `{target.display_name}`에 대한 단기 기억 후보 S{result.index}번을 지웠어."
        )
    elif result.memory_type == LONG_TERM_MEMORY_KEY:
        await message.channel.send(f"…응. `{target.display_name}`에 대한 {result.index}번 평가를 지웠어.")
    else:
        await message.channel.send(f"…응. `{target.display_name}`에 대한 기억을 지웠어.")


async def _send_or_update_reasoning(
    message: discord.Message,
    raw_text: str,
    room_key: str,
    room_data: dict,
) -> None:
    raw_value = raw_text.strip()
    if not raw_value or raw_value in {"상태", "확인", "보기"}:
        await message.channel.send(f"…이 방의 추론 단계는 `{format_reasoning_status(room_data)}`야.")
        return

    effort = set_room_reasoning_effort(room_data, raw_value)
    if effort is None:
        await message.channel.send("…추론 단계는 `없음`, `낮음`, `보통`, `높음` 중 하나로 적어줘. 예: `/추론 높음`")
        return

    update_room_data(room_key, room_data)
    await message.channel.send(f"…응. 이 방의 추론 단계를 `{reasoning_effort_label(effort)}`으로 맞췄어.")


def _target_to_user_like(target: object) -> object:
    display_name = getattr(target, "display_name", "알 수 없음")
    return SimpleNamespace(
        id=getattr(target, "user_id", None),
        mention=getattr(target, "mention", None) or f"`{getattr(target, 'user_id', '알 수 없음')}`",
        display_name=display_name,
        name=display_name,
        display_avatar=None,
    )


async def _resolve_target_argument(
    message: discord.Message,
    client: discord.Client,
    raw_text: str,
) -> tuple[object | None, dict | None, str, str | None]:
    target, remainder, error_message = await resolve_explicit_user_target(
        message=message,
        client=client,
        argument_text=raw_text,
    )
    if error_message or target is None:
        return None, None, "", error_message or "…대상 사용자를 찾지 못했어."
    return target, dict(target.user_data or {}), remainder, None


async def _send_file_path(message: discord.Message, path, *, missing_message: str) -> None:
    try:
        if not path.exists() or not path.is_file():
            await message.channel.send(missing_message)
            return
        size = path.stat().st_size
        if size > MAX_MEMORY_FILE_SEND_BYTES:
            await message.channel.send(
                f"…`{path.name}` 파일이 너무 커서 여기로 바로 보낼 수 없어. "
                f"현재 크기는 약 {size / 1024 / 1024:.1f}MB야."
            )
            return
        await message.channel.send(file=discord.File(str(path), filename=path.name))
    except OSError:
        await message.channel.send(f"…`{path.name}` 파일에 접근하지 못했어. 파일 권한이나 저장 위치를 확인해줘.")


def _matched_memory_file_alias(user_text: str) -> str | None:
    for alias in MEMORY_FILE_COMMAND_ALIASES:
        if matches_command(user_text, alias):
            return alias
    return None


async def _send_memory_or_recording_file(message: discord.Message, filename: str | None = None) -> None:
    if not filename:
        path = ensure_memory_section_file("conversation")
        await _send_file_path(message, path, missing_message="…대화 메모리 파일을 찾지 못했어.")
        return

    section = resolve_memory_section(filename)
    if section:
        path = ensure_memory_section_file(section)
        await _send_file_path(
            message,
            path,
            missing_message=f"…{MEMORY_SECTION_LABELS[section]} 메모리 파일을 찾지 못했어.",
        )
        return

    try:
        resolved_filename = resolve_recording_reference(filename, allow_plain_index=True)
        path = get_recording_path(resolved_filename)
    except VoiceRecordNotFound:
        await message.channel.send("…그 이름의 통화 기록 파일을 찾지 못했어. `/대화목록`으로 파일명을 확인해줘.")
        return

    await _send_file_path(message, path, missing_message="…그 통화 기록 파일을 찾지 못했어.")


async def _generate_adapter_reply(
    *,
    message: discord.Message,
    prompt: str,
    room_key: str,
    extra_context: str | None,
    force_web_search: bool,
    allow_command_output: bool,
) -> str:
    async with message.channel.typing():
        display_name = getattr(message.author, "display_name", message.author.name)
        return await generate_reply(
            user_message=prompt,
            user_id=message.author.id,
            display_name=display_name,
            room_key=room_key,
            extra_context=extra_context,
            force_web_search=force_web_search,
            allow_command_output=allow_command_output,
            persist_command_reply=False,
        )


async def _run_command_adapter(
    *,
    message: discord.Message,
    raw_text: str,
    user_data: dict,
    room_key: str,
    room_data: dict,
    client: discord.Client,
    force_web_search: bool = False,
    allow_prompt_only: bool = False,
) -> None:
    try:
        request = parse_command_adapter_args(raw_text, allow_prompt_only=allow_prompt_only)
    except CommandUsageError as exc:
        await message.channel.send(str(exc))
        return

    await _run_command_adapter_request(
        message=message,
        request=request,
        user_data=user_data,
        room_key=room_key,
        room_data=room_data,
        client=client,
        force_web_search=force_web_search,
    )


async def _run_command_adapter_request(
    *,
    message: discord.Message,
    request: CommandAdapterRequest,
    user_data: dict,
    room_key: str,
    room_data: dict,
    client: discord.Client,
    force_web_search: bool = False,
) -> None:

    for command_text in request.command_texts:
        if not _adapter_command_allowed(command_text):
            await message.channel.send(_adapter_blocked_message(command_text))
            return

    if not request.command_texts:
        reply = await _generate_adapter_reply(
            message=message,
            prompt=request.prompt,
            room_key=room_key,
            extra_context=None,
            force_web_search=force_web_search,
            allow_command_output=False,
        )
        await message.channel.send(reply[:1900])
        return

    capture_channel = _CommandCaptureChannel(message.channel)
    capture_message = _CommandCaptureMessage(message, capture_channel)
    command_summaries = []
    command_queue = deque(request.command_texts)

    while True:
        while command_queue:
            if len(command_summaries) >= MAX_ADAPTER_COMMANDS:
                await message.channel.send(ADAPTER_CHAIN_LIMIT_MESSAGE)
                return

            command_text = command_queue.popleft()
            if not _adapter_command_allowed(command_text):
                await message.channel.send(_adapter_blocked_message(command_text))
                return

            output_start = len(capture_channel.outputs)
            try:
                await handle_mentioned_message(
                    message=capture_message,
                    user_text=command_text,
                    user_data=user_data,
                    room_key=room_key,
                    room_data=room_data,
                    client=client,
                )
            except Exception as exc:
                print("Command adapter execution error:", exc)
                await message.channel.send("…명령어 실행 중 오류가 났어. 결과를 반영한 답변은 만들지 않을게.")
                return

            command_output = "\n".join(capture_channel.outputs[output_start:]).strip()
            if not command_output:
                command_output = "명령어가 실행됐지만 표시된 결과 메시지는 없었어."
            command_summaries.append(
                _format_adapter_command_summary(
                    len(command_summaries) + 1,
                    command_text,
                    command_output,
                )
            )

        extra_context = _format_adapter_context(command_summaries)
        allow_more_commands = len(command_summaries) < MAX_ADAPTER_COMMANDS

        reply = await _generate_adapter_reply(
            message=message,
            prompt=request.prompt,
            room_key=room_key,
            extra_context=extra_context,
            force_web_search=force_web_search,
            allow_command_output=allow_more_commands,
        )

        followup_command = _extract_auto_command(reply)
        if not followup_command:
            await message.channel.send(reply[:1900])
            return

        if len(command_summaries) >= MAX_ADAPTER_COMMANDS:
            await message.channel.send(ADAPTER_CHAIN_LIMIT_MESSAGE)
            return

        if not _adapter_command_allowed(followup_command):
            await message.channel.send(_adapter_blocked_message(followup_command))
            return

        command_queue.append(followup_command)


async def _run_tool_plan(
    *,
    plan: ToolPlan,
    message: discord.Message,
    user_text: str,
    user_data: dict,
    room_key: str,
    room_data: dict,
    client: discord.Client,
) -> bool:
    if plan.mode == PLAN_CHAT:
        return False

    if plan.mode in {PLAN_CLARIFY, PLAN_REJECT}:
        await message.channel.send(plan.response[:1900])
        return True

    if plan.mode not in {PLAN_COMMAND, PLAN_COMMAND_THEN_REPLY}:
        return False

    commands = tuple(command for command in plan.commands if command.startswith("/"))
    _, commands = _split_state_update_commands(commands)
    if not commands:
        return False
    if len(commands) > MAX_ADAPTER_COMMANDS:
        await message.channel.send(ADAPTER_CHAIN_LIMIT_MESSAGE)
        return True

    if plan.mode == PLAN_COMMAND_THEN_REPLY:
        await _run_command_adapter_request(
            message=message,
            request=CommandAdapterRequest(command_texts=commands, prompt=user_text),
            user_data=user_data,
            room_key=room_key,
            room_data=room_data,
            client=client,
        )
        return True

    for command_text in commands:
        await handle_mentioned_message(
            message=message,
            user_text=command_text,
            user_data=user_data,
            room_key=room_key,
            room_data=room_data,
            client=client,
        )
    return True


async def handle_mentioned_message(
    message: discord.Message,
    user_text: str,
    user_data: dict,
    room_key: str,
    room_data: dict,
    client: discord.Client,
    attachment_context: str | None = None,
) -> None:
    author_id = message.author.id
    special_user = is_special_user(author_id)
    planner_chat_only = False
    state_affection_updated = False

    if not attachment_context and not user_text.strip().startswith("/"):
        display_name = getattr(message.author, "display_name", message.author.name)
        tool_plan = await plan_tool_use(
            user_message=user_text,
            user_id=author_id,
            display_name=display_name,
            room_key=room_key,
            special_user=special_user,
        )
        if tool_plan is not None:
            if tool_plan.mode == PLAN_CHAT:
                planner_chat_only = True
            elif await _run_tool_plan(
                plan=tool_plan,
                message=message,
                user_text=user_text,
                user_data=user_data,
                room_key=room_key,
                room_data=room_data,
                client=client,
            ):
                return

    voice_search_alias = matched_alias(user_text, VOICE_SEARCH_COMMAND.aliases)
    if voice_search_alias:
        if not special_user:
            await message.channel.send("…그 명령어를 사용할 권한이 없어.")
            return
        await _send_voice_search(message, _command_arg(user_text, voice_search_alias))
        return

    admin_status_alias = matched_alias(user_text, ADMIN_STATUS_COMMAND.aliases)
    if admin_status_alias:
        if not special_user:
            await message.channel.send("…그 명령어를 사용할 권한이 없어.")
            return
        await _send_admin_status(message, room_key, room_data)
        return

    role_alias = matched_alias(user_text, ROLE_COMMAND.aliases)
    if role_alias:
        if not special_user:
            await message.channel.send("…그 명령어를 사용할 권한이 없어.")
            return
        await handle_role_command(message, _command_arg(user_text, role_alias))
        return

    for reasoning_alias in ("/추론", "/추론설정"):
        if matches_command(user_text, reasoning_alias):
            if not special_user:
                await message.channel.send("…추론 설정을 바꿀 권한이 없어.")
                return
            await _send_or_update_reasoning(
                message,
                _command_arg(user_text, reasoning_alias),
                room_key,
                room_data,
            )
            return

    if matches_command(user_text, "/뇌"):
        if not special_user:
            await message.channel.send("…반디의 뇌를 볼 권한이 없어.")
            return
        await _send_brain_notes(message, client, _command_arg(user_text, "/뇌"))
        return

    if matches_command(user_text, "/뇌추가"):
        if not special_user:
            await message.channel.send("…반디의 뇌를 바꿀 권한이 없어.")
            return
        await _add_brain_note(message, client, _command_arg(user_text, "/뇌추가"))
        return

    if matches_command(user_text, "/뇌수정"):
        if not special_user:
            await message.channel.send("…반디의 뇌를 바꿀 권한이 없어.")
            return
        await _update_brain_note(message, client, _command_arg(user_text, "/뇌수정"))
        return

    if matches_command(user_text, "/뇌삭제"):
        if not special_user:
            await message.channel.send("…반디의 뇌를 바꿀 권한이 없어.")
            return
        await _delete_brain_note(message, client, _command_arg(user_text, "/뇌삭제"))
        return

    for adapter_alias in ("/실행", "/명령답변"):
        if matches_command(user_text, adapter_alias):
            await _run_command_adapter(
                message=message,
                raw_text=_command_arg(user_text, adapter_alias),
                user_data=user_data,
                room_key=room_key,
                room_data=room_data,
                client=client,
            )
            return

    for web_adapter_alias in ("/검색실행", "/인터넷실행", "/검색답변"):
        if matches_command(user_text, web_adapter_alias):
            if not special_user:
                await message.channel.send("…인터넷 검색 실행 권한이 없어.")
                return
            await _run_command_adapter(
                message=message,
                raw_text=_command_arg(user_text, web_adapter_alias),
                user_data=user_data,
                room_key=room_key,
                room_data=room_data,
                client=client,
                force_web_search=True,
                allow_prompt_only=True,
            )
            return

    if is_news_command_text(user_text):
        await handle_news_command(message, user_text, client)
        return

    if matches_command(user_text, "/프로필"):
        target_mentions = get_target_mentions(message, client.user)
        target_user = target_mentions[0] if target_mentions else message.author
        display_name = getattr(target_user, "display_name", target_user.name)
        target_data = get_user_data(target_user.id, display_name)
        await message.channel.send(embed=create_profile_embed(target_user, target_data))
        return

    if matches_command(user_text, "/주사위"):
        try:
            request = parse_dice_args(_command_arg(user_text, "/주사위"))
            result = roll_dice(request)
        except CommandUsageError as exc:
            await message.channel.send(str(exc))
            return
        await message.channel.send(format_dice_result(result))
        return

    for team_alias in ("/팀나누기", "/팀"):
        if matches_command(user_text, team_alias):
            try:
                request = parse_team_split_args(_command_arg(user_text, team_alias))
                teams = split_members_into_teams(request)
            except CommandUsageError as exc:
                await message.channel.send(str(exc))
                return
            await message.channel.send(format_team_split_result(request, teams))
            return

    if matches_command(user_text, "/기록"):
        if not special_user:
            await message.channel.send("…통화 기록 권한이 없어.")
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
            await message.channel.send("…통화 기록 권한이 없어.")
            return

        if message.guild is None:
            await message.channel.send("…서버 안에서만 기록을 멈출 수 있어.")
            return

        _, response_text, _ = await stop_voice_recording(message.guild.id)
        await message.channel.send(response_text)
        return

    if matches_command(user_text, "/대화목록"):
        if not special_user:
            await message.channel.send("…통화 기록 목록을 볼 권한이 없어.")
            return
        await _send_recording_list(message)
        return

    memory_file_alias = _matched_memory_file_alias(user_text)
    if memory_file_alias:
        if not special_user:
            await message.channel.send("…메모리 파일을 받을 권한이 없어.")
            return
        filename = _command_arg(user_text, memory_file_alias) or None
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
            await message.channel.send("…메모리 초기화 권한이 없어.")
            return

        raw_args = user_text.replace(memory_reset_command, "", 1).strip()
        section, confirm_text = _parse_memory_reset_args(raw_args)
        if section is None or confirm_text != "확인":
            await message.channel.send(
                "…초기화할 메모리 파일 이름과 `확인`을 같이 적어줘.\n"
                f"{format_memory_section_list()}\n"
                "예: `/메모리초기화 대화 확인`, `/메모리초기화 news_memory.json 확인`"
            )
            return

        reset_memory_section(section)
        if section == "polls":
            cancel_poll_tasks()
        label = MEMORY_SECTION_LABELS[section]
        path = get_memory_section_file(section)
        await message.channel.send(f"…응. {label} 메모리 파일 `{path.name}`을 비웠어.")
        return

    if special_user and user_text.startswith("/유저정보"):
        target, target_data, _, error_message = await _resolve_target_argument(
            message,
            client,
            _command_arg(user_text, "/유저정보"),
        )
        if error_message or target is None or target_data is None:
            await message.channel.send(error_message or "…대상 사용자를 찾지 못했어.")
            return

        await message.channel.send(embed=create_user_info_embed(_target_to_user_like(target), target_data))
        return

    if special_user and user_text.startswith("/호감도설정 "):
        target, _, args, error_message = await _resolve_target_argument(
            message,
            client,
            _command_arg(user_text, "/호감도설정"),
        )
        if error_message or target is None:
            await message.channel.send(error_message or "…대상 사용자를 찾지 못했어.")
            return

        value = parse_last_int_arg(args)
        if value is None:
            await message.channel.send("…대상과 숫자를 같이 적어줘. 예: `/호감도설정 @유저 75`")
            return

        new_value = set_user_affection(target.user_id, value)

        if target.user_id == SPECIAL_USER_ID:
            await message.channel.send("…그 대상의 호감도는 변경할 수 없어.")
        else:
            await message.channel.send(f"…{target.display_name}의 호감도를 {new_value}로 맞춰뒀어.")
        return

    if special_user and user_text.startswith("/호감도증감 "):
        target, _, args, error_message = await _resolve_target_argument(
            message,
            client,
            _command_arg(user_text, "/호감도증감"),
        )
        if error_message or target is None:
            await message.channel.send(error_message or "…대상 사용자를 찾지 못했어.")
            return

        delta = parse_last_int_arg(args)
        if delta is None:
            await message.channel.send("…대상과 증감할 숫자를 같이 적어줘. 예: `/호감도증감 @유저 5`")
            return

        new_value = change_user_affection(target.user_id, delta)

        if target.user_id == SPECIAL_USER_ID:
            await message.channel.send("…그 대상의 호감도는 변경할 수 없어.")
        else:
            sign = "+" if delta >= 0 else ""
            await message.channel.send(
                f"…{target.display_name}의 호감도를 {sign}{delta}만큼 조정했어. 지금은 {new_value}야."
            )
        return

    if user_text == "/호감도":
        if special_user:
            await message.channel.send("…굳이 숫자로 말하지 않을게. 지금은 충분히 가까운 편이야.")
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
        await handle_nickname_command(
            message=message,
            argument_text=user_text.replace("/호칭 ", "", 1),
            user_data=user_data,
            client=client,
            special_user=special_user,
        )
        return

    if matches_command(user_text, "/투표"):
        if not special_user:
            await message.channel.send("…투표 기능을 사용할 권한이 없어.")
            return

        await create_poll_from_command(message, user_text, client)
        return

    if matches_command(user_text, "/투표마감"):
        if not special_user:
            await message.channel.send("…투표 마감 권한이 없어.")
            return

        await close_poll_from_command(message, client, user_text)
        return

    if user_text == "/요약" or user_text.startswith("/요약 "):
        recording_filename = _summary_recording_filename(user_text)
        if recording_filename:
            if not special_user:
                await message.channel.send("…통화 기록 요약 권한이 없어.")
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
            f"- 추론 단계: {format_reasoning_status(room_data)}\n"
            f"- 저장된 방 대화 수: {len(room_data.get('history', []))}"
        )
        return

    if user_text == "/도움말":
        embed = create_special_help_embed() if special_user else create_help_embed()
        await message.channel.send(embed=embed)
        return

    if user_text.startswith("/") and not special_user and is_special_only_command(user_text):
        await message.channel.send(PERMISSION_DENIED_MESSAGE)
        return

    if user_text.startswith("/"):
        await message.channel.send("그 명령어는 잘 모르겠어. '/도움말'을 불러서 사용 가능한 명령어들을 확인해봐.")
        return

    display_name = getattr(message.author, "display_name", message.author.name)
    state_update_commands = await plan_state_updates(
        user_message=user_text,
        user_id=author_id,
        display_name=display_name,
        room_key=room_key,
        attachment_context=attachment_context,
    )
    if state_update_commands:
        state_update_result = await _run_silent_state_update_commands(
            commands=state_update_commands,
            message=message,
            room_key=room_key,
            room_data=room_data,
            client=client,
        )
        state_affection_updated = state_update_result.affection_updated

    async with message.channel.typing():
        reply = await generate_reply(
            user_message=user_text,
            user_id=author_id,
            display_name=display_name,
            room_key=room_key,
            attachment_context=attachment_context,
            allow_command_output=not planner_chat_only,
            persist_command_reply=False,
            apply_affection_adjustment=not state_affection_updated,
        )

    if not planner_chat_only and await _run_auto_command_from_reply(
        reply=reply,
        message=message,
        user_text=user_text,
        user_data=user_data,
        room_key=room_key,
        room_data=room_data,
        client=client,
    ):
        return

    await message.channel.send(reply[:1900])
