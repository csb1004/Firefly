import asyncio
import logging

import discord
from discord import app_commands

from firefly.commands import handle_mentioned_message
from firefly.config import DISCORD_BOT_TOKEN, MEMORY_FILE, SPECIAL_USER_ID
from firefly.news import handle_news_command, is_news_command_text, start_daily_news_task
from firefly.polls import enforce_single_vote, finalize_poll, refresh_poll_vote_count, restore_poll_tasks
from firefly.storage import (
    get_existing_room_data,
    get_room_data,
    get_room_key,
    get_user_data,
    record_room_user_message,
)
from firefly.text_utils import clean_discord_content, is_command_text
from firefly.voice import handle_bot_voice_disconnect, start_voice_recording, stop_voice_recording
from firefly.voice_records import (
    VoiceRecordNotFound,
    format_recording_list,
    get_recording_path,
    list_recordings,
    purge_expired_recordings,
)

logging.getLogger("discord.ext.voice_recv.reader").setLevel(logging.WARNING)

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.voice_states = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
news_group = app_commands.Group(name="최신소식", description="기술 소식 구독과 설정을 관리해요.")
topic_group = app_commands.Group(name="주제", description="최신 소식 주제를 확인하거나 관리해요.")
_slash_commands_synced = False
_voice_cleanup_task_started = False


class _SlashTyping:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _SlashChannel:
    def __init__(
        self,
        interaction: discord.Interaction,
        channel: discord.abc.Messageable,
        *,
        ephemeral: bool,
    ):
        self._interaction = interaction
        self._channel = channel
        self._ephemeral = ephemeral

    def typing(self):
        return _SlashTyping()

    async def send(self, *args, **kwargs):
        if self._ephemeral:
            kwargs["ephemeral"] = True
            return await self._interaction.followup.send(*args, **kwargs)
        return await self._channel.send(*args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._channel, name)


class _SlashMessage:
    def __init__(
        self,
        interaction: discord.Interaction,
        *,
        mentions: list[discord.User | discord.Member] | None = None,
        reference_message_id: int | None = None,
        ephemeral: bool = False,
    ):
        self.author = interaction.user
        self.channel = _SlashChannel(interaction, interaction.channel, ephemeral=ephemeral)
        self.guild = interaction.guild
        self.mentions = mentions or []
        self.reference = (
            discord.MessageReference(message_id=reference_message_id)
            if reference_message_id is not None
            else None
        )


def _message_mentions_user(message: discord.Message, user: object) -> bool:
    return any(getattr(mention, "id", None) == user.id for mention in message.mentions)


def _mention_text(user: discord.User | discord.Member | None) -> str:
    return user.mention if user is not None else ""


async def _run_text_command_slash(
    interaction: discord.Interaction,
    user_text: str,
    *,
    mentions: list[discord.User | discord.Member] | None = None,
    reference_message_id: int | None = None,
    ephemeral: bool = False,
) -> None:
    if interaction.channel is None:
        await interaction.response.send_message("…채널 안에서만 사용할 수 있어.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True, ephemeral=ephemeral)

    message = _SlashMessage(
        interaction,
        mentions=mentions,
        reference_message_id=reference_message_id,
        ephemeral=ephemeral,
    )
    room_key = get_room_key(message)
    room_data = get_room_data(room_key)
    display_name = getattr(interaction.user, "display_name", interaction.user.name)
    user_data = get_user_data(interaction.user.id, display_name)

    await handle_mentioned_message(
        message=message,
        user_text=user_text,
        user_data=user_data,
        room_key=room_key,
        room_data=room_data,
        client=client,
    )

    try:
        await interaction.delete_original_response()
    except (discord.NotFound, discord.HTTPException):
        pass


async def _require_special_interaction(interaction: discord.Interaction) -> bool:
    if interaction.user.id == SPECIAL_USER_ID:
        return True

    text = "…그 명령어는 특별 사용자만 사용할 수 있어."
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True)
    else:
        await interaction.response.send_message(text, ephemeral=True)
    return False


async def _voice_record_cleanup_loop() -> None:
    while True:
        purge_expired_recordings()
        await asyncio.sleep(6 * 60 * 60)


@tree.command(name="도움말", description="사용 가능한 명령어 목록을 보여줘요.")
async def help_slash(interaction: discord.Interaction):
    await _run_text_command_slash(interaction, "/도움말", ephemeral=True)


@tree.command(name="호감도", description="현재 너에 대한 반디의 호감도를 확인해요.")
async def affection_slash(interaction: discord.Interaction):
    await _run_text_command_slash(interaction, "/호감도", ephemeral=True)


@tree.command(name="초기화", description="최근 개인 대화 기억을 비워요.")
async def reset_slash(interaction: discord.Interaction):
    await _run_text_command_slash(interaction, "/초기화", ephemeral=True)


@tree.command(name="호칭", description="반디가 너를 부를 호칭을 바꿔요.")
@app_commands.rename(nickname="이름")
@app_commands.describe(nickname="새로 사용할 호칭")
async def nickname_slash(interaction: discord.Interaction, nickname: str):
    await _run_text_command_slash(interaction, f"/호칭 {nickname}", ephemeral=True)


@tree.command(name="기록", description="현재 들어가 있는 통화방의 대화를 전사해서 저장해요.")
async def record_slash(interaction: discord.Interaction):
    if not await _require_special_interaction(interaction):
        return

    if interaction.channel is None:
        await interaction.response.send_message("…서버 채널 안에서만 기록을 시작할 수 있어.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    _, response_text, _ = await start_voice_recording(
        client,
        user=interaction.user,
        text_channel=interaction.channel,
    )
    await interaction.followup.send(response_text)


@tree.command(name="기록중지", description="진행 중인 통화 기록을 마쳐요.")
async def stop_record_slash(interaction: discord.Interaction):
    if not await _require_special_interaction(interaction):
        return

    if interaction.guild is None:
        await interaction.response.send_message("…서버 안에서만 기록을 멈출 수 있어.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    _, response_text, _ = await stop_voice_recording(interaction.guild.id)
    await interaction.followup.send(response_text)


@tree.command(name="대화목록", description="최근 7일 동안 저장된 통화 기록 파일 목록을 보여줘요.")
async def recording_list_slash(interaction: discord.Interaction):
    if not await _require_special_interaction(interaction):
        return

    records = list_recordings()
    await interaction.response.send_message(format_recording_list(records), ephemeral=True)


@tree.command(name="기록검색", description="저장된 통화 기록에서 질문이나 키워드로 필요한 내용을 찾아요.")
@app_commands.rename(query="질문")
@app_commands.describe(query="예: 누가 뭘 먹기로 했는지 알려줘")
async def recording_search_slash(interaction: discord.Interaction, query: str):
    await _run_text_command_slash(interaction, f"/기록검색 {query}", ephemeral=True)


@tree.command(name="봇상태", description="메모리, 뉴스, 투표, 통화 기록 상태를 확인해요. 특별 사용자 전용.")
async def bot_status_slash(interaction: discord.Interaction):
    await _run_text_command_slash(interaction, "/봇상태", ephemeral=True)


@tree.command(name="요약", description="최근 개인/방 대화 또는 통화 기록 파일을 요약해요.")
@app_commands.rename(target="대상", limit="개수")
@app_commands.describe(
    target="개인, 방, 또는 대화목록에 표시된 통화 기록 파일명",
    limit="최근 몇 개 메시지를 요약할지",
)
async def summary_slash(
    interaction: discord.Interaction,
    target: str | None = None,
    limit: int | None = None,
):
    parts = ["/요약"]
    if target:
        parts.append(target)
    if limit is not None:
        parts.append(str(limit))
    await _run_text_command_slash(interaction, " ".join(parts), ephemeral=True)


@tree.command(name="메모리파일", description="memory.json 또는 통화 기록 원본 파일을 받아와요.")
@app_commands.rename(filename="파일이름")
@app_commands.describe(filename="생략하면 memory.json, 입력하면 통화 기록 파일명")
async def memory_file_slash(interaction: discord.Interaction, filename: str | None = None):
    if not await _require_special_interaction(interaction):
        return

    await interaction.response.defer(thinking=True, ephemeral=True)

    if not filename:
        if not MEMORY_FILE.exists():
            await interaction.followup.send("…아직 저장된 메모리 파일이 없어.", ephemeral=True)
            return
        await interaction.followup.send(file=discord.File(str(MEMORY_FILE)), ephemeral=True)
        return

    try:
        path = get_recording_path(filename)
    except VoiceRecordNotFound:
        await interaction.followup.send("…그 이름의 통화 기록 파일을 찾지 못했어. `/대화목록`으로 확인해줘.", ephemeral=True)
        return

    await interaction.followup.send(file=discord.File(str(path), filename=path.name), ephemeral=True)


@tree.command(name="메모리초기화", description="memory.json 전체를 비워요. 특별 사용자 전용.")
@app_commands.rename(confirm_text="확인문구")
@app_commands.describe(confirm_text="정말 초기화하려면 확인이라고 입력")
async def memory_reset_slash(interaction: discord.Interaction, confirm_text: str):
    await _run_text_command_slash(
        interaction,
        f"/메모리초기화 {confirm_text}",
        ephemeral=True,
    )


@tree.command(name="메모리파일초기화", description="memory.json 전체를 비워요. 특별 사용자 전용.")
@app_commands.rename(confirm_text="확인문구")
@app_commands.describe(confirm_text="정말 초기화하려면 확인이라고 입력")
async def memory_file_reset_slash(interaction: discord.Interaction, confirm_text: str):
    await _run_text_command_slash(
        interaction,
        f"/메모리파일초기화 {confirm_text}",
        ephemeral=True,
    )


@tree.command(name="유저정보", description="유저의 저장 정보와 최근 대화를 확인해요. 특별 사용자 전용.")
@app_commands.rename(target="유저")
@app_commands.describe(target="확인할 유저")
async def user_info_slash(interaction: discord.Interaction, target: discord.User):
    await _run_text_command_slash(
        interaction,
        f"/유저정보 {_mention_text(target)}",
        mentions=[target],
        ephemeral=True,
    )


@tree.command(name="호감도설정", description="유저의 호감도를 특정 값으로 맞춰요. 특별 사용자 전용.")
@app_commands.rename(target="유저", value="숫자")
@app_commands.describe(target="대상 유저", value="설정할 호감도")
async def set_affection_slash(interaction: discord.Interaction, target: discord.User, value: int):
    await _run_text_command_slash(
        interaction,
        f"/호감도설정 {_mention_text(target)} {value}",
        mentions=[target],
        ephemeral=True,
    )


@tree.command(name="호감도증감", description="유저의 호감도를 증감해요. 특별 사용자 전용.")
@app_commands.rename(target="유저", delta="숫자")
@app_commands.describe(target="대상 유저", delta="더하거나 뺄 값")
async def change_affection_slash(interaction: discord.Interaction, target: discord.User, delta: int):
    await _run_text_command_slash(
        interaction,
        f"/호감도증감 {_mention_text(target)} {delta}",
        mentions=[target],
        ephemeral=True,
    )


@tree.command(name="투표", description="투표를 만들어요. 특별 사용자 전용.")
@app_commands.rename(poll_text="내용")
@app_commands.describe(poll_text="예: 저녁 메뉴 | 항목수=3 | 치킨 | 피자 | 떡볶이 | 10분")
async def poll_slash(interaction: discord.Interaction, poll_text: str):
    await _run_text_command_slash(interaction, f"/투표 {poll_text}")


@tree.command(name="투표마감", description="진행 중인 투표를 마감해요. 특별 사용자 전용.")
@app_commands.rename(message_id="메시지id")
@app_commands.describe(message_id="마감할 투표 메시지 ID")
async def close_poll_slash(interaction: discord.Interaction, message_id: str):
    if not await _require_special_interaction(interaction):
        return

    if not message_id.isdigit():
        await interaction.response.send_message("…투표 메시지 ID는 숫자로 적어줘.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    closed_by = getattr(interaction.user, "display_name", interaction.user.name)
    closed = await finalize_poll(client, int(message_id), closed_by=closed_by)
    if closed:
        await interaction.followup.send("…투표를 마감했어.", ephemeral=True)
    else:
        await interaction.followup.send("…진행 중인 투표를 찾지 못했어.", ephemeral=True)


@tree.command(name="인터넷모드", description="이 방의 인터넷 검색 모드를 켜거나 꺼요. 특별 사용자 전용.")
@app_commands.rename(value="값")
@app_commands.describe(value="on 또는 off")
@app_commands.choices(
    value=[
        app_commands.Choice(name="on", value="on"),
        app_commands.Choice(name="off", value="off"),
    ]
)
async def internet_mode_slash(interaction: discord.Interaction, value: app_commands.Choice[str]):
    await _run_text_command_slash(interaction, f"/인터넷모드 {value.value}", ephemeral=True)


@tree.command(name="단체모드", description="이 방의 단체 대화 기억 모드를 켜거나 꺼요. 특별 사용자 전용.")
@app_commands.rename(value="값")
@app_commands.describe(value="on 또는 off")
@app_commands.choices(
    value=[
        app_commands.Choice(name="on", value="on"),
        app_commands.Choice(name="off", value="off"),
    ]
)
async def group_mode_slash(interaction: discord.Interaction, value: app_commands.Choice[str]):
    await _run_text_command_slash(interaction, f"/단체모드 {value.value}", ephemeral=True)


@tree.command(name="방기억", description="현재 방의 단체 모드 기억을 보여줘요. 특별 사용자 전용.")
async def room_history_slash(interaction: discord.Interaction):
    await _run_text_command_slash(interaction, "/방기억", ephemeral=True)


@tree.command(name="방초기화", description="현재 방의 단체 기억을 비워요. 특별 사용자 전용.")
async def room_reset_slash(interaction: discord.Interaction):
    await _run_text_command_slash(interaction, "/방초기화", ephemeral=True)


@tree.command(name="방상태", description="현재 방의 인터넷/단체 모드 상태를 보여줘요. 특별 사용자 전용.")
async def room_status_slash(interaction: discord.Interaction):
    await _run_text_command_slash(interaction, "/방상태", ephemeral=True)


@news_group.command(name="받기", description="최신 소식 개인 메시지를 구독해요.")
@app_commands.rename(target="유저")
@app_commands.describe(target="특별 사용자만 다른 사람을 지정할 수 있어요.")
async def news_subscribe_slash(interaction: discord.Interaction, target: discord.User | None = None):
    user_text = f"/최신 소식 받기 {_mention_text(target)}".strip()
    await _run_text_command_slash(
        interaction,
        user_text,
        mentions=[target] if target is not None else None,
        ephemeral=True,
    )


@news_group.command(name="그만", description="최신 소식 개인 메시지 구독을 해제해요.")
@app_commands.rename(target="유저")
@app_commands.describe(target="특별 사용자만 다른 사람을 지정할 수 있어요.")
async def news_unsubscribe_slash(interaction: discord.Interaction, target: discord.User | None = None):
    user_text = f"/최신 소식 그만 {_mention_text(target)}".strip()
    await _run_text_command_slash(
        interaction,
        user_text,
        mentions=[target] if target is not None else None,
        ephemeral=True,
    )


@news_group.command(name="상태", description="최신 소식 구독과 발송 설정을 보여줘요.")
async def news_status_slash(interaction: discord.Interaction):
    await _run_text_command_slash(interaction, "/최신 소식 상태", ephemeral=True)


@news_group.command(name="목록", description="최신 소식 구독자 목록과 설정을 보여줘요.")
async def news_list_slash(interaction: discord.Interaction):
    await _run_text_command_slash(interaction, "/최신 소식 목록", ephemeral=True)


@news_group.command(name="시간", description="최신 소식 발송 시간을 보거나 바꿔요. 변경은 특별 사용자 전용.")
@app_commands.rename(time_text="시간")
@app_commands.describe(time_text="예: 09:00, 오전 9시. 비워두면 현재 시간을 보여줘요.")
async def news_time_slash(interaction: discord.Interaction, time_text: str | None = None):
    user_text = f"/최신 소식 시간 {time_text or ''}".strip()
    await _run_text_command_slash(interaction, user_text, ephemeral=True)


@news_group.command(name="중복초기화", description="이미 보낸 최신 소식 기록을 비워요. 특별 사용자 전용.")
@app_commands.rename(confirm_text="확인문구")
@app_commands.describe(confirm_text="정말 비우려면 확인이라고 입력")
async def news_history_reset_slash(interaction: discord.Interaction, confirm_text: str):
    await _run_text_command_slash(interaction, f"/최신 소식 중복초기화 {confirm_text}", ephemeral=True)


@news_group.command(name="중복삭제", description="이미 보낸 최신 소식 기록을 비워요. 특별 사용자 전용.")
@app_commands.rename(confirm_text="확인문구")
@app_commands.describe(confirm_text="정말 비우려면 확인이라고 입력")
async def news_history_delete_slash(interaction: discord.Interaction, confirm_text: str):
    await _run_text_command_slash(interaction, f"/최신 소식 중복삭제 {confirm_text}", ephemeral=True)


@news_group.command(name="기록초기화", description="이미 보낸 최신 소식 기록을 비워요. 특별 사용자 전용.")
@app_commands.rename(confirm_text="확인문구")
@app_commands.describe(confirm_text="정말 비우려면 확인이라고 입력")
async def news_record_reset_slash(interaction: discord.Interaction, confirm_text: str):
    await _run_text_command_slash(interaction, f"/최신 소식 기록초기화 {confirm_text}", ephemeral=True)


@news_group.command(name="중복기록초기화", description="이미 보낸 최신 소식 기록을 비워요. 특별 사용자 전용.")
@app_commands.rename(confirm_text="확인문구")
@app_commands.describe(confirm_text="정말 비우려면 확인이라고 입력")
async def news_duplicate_record_reset_slash(interaction: discord.Interaction, confirm_text: str):
    await _run_text_command_slash(interaction, f"/최신 소식 중복기록초기화 {confirm_text}", ephemeral=True)


@topic_group.command(name="목록", description="최신 소식 주제를 보여줘요.")
async def topic_list_slash(interaction: discord.Interaction):
    await _run_text_command_slash(interaction, "/주제 목록", ephemeral=True)


@topic_group.command(name="추가", description="최신 소식 주제를 추가해요. 특별 사용자 전용.")
@app_commands.rename(topic="주제")
@app_commands.describe(topic="추가할 주제")
async def topic_add_slash(interaction: discord.Interaction, topic: str):
    await _run_text_command_slash(interaction, f"/주제 추가 {topic}", ephemeral=True)


@topic_group.command(name="제거", description="최신 소식 주제를 제거해요. 특별 사용자 전용.")
@app_commands.rename(topic="주제")
@app_commands.describe(topic="제거할 주제")
async def topic_remove_slash(interaction: discord.Interaction, topic: str):
    await _run_text_command_slash(interaction, f"/주제 제거 {topic}", ephemeral=True)


@topic_group.command(name="설정", description="최신 소식 주제 목록을 새로 설정해요. 특별 사용자 전용.")
@app_commands.rename(topics="주제목록")
@app_commands.describe(topics="쉼표로 구분한 주제 목록")
async def topic_set_slash(interaction: discord.Interaction, topics: str):
    await _run_text_command_slash(interaction, f"/주제 설정 {topics}", ephemeral=True)


@topic_group.command(name="변경", description="최신 소식 주제 목록을 새로 변경해요. 특별 사용자 전용.")
@app_commands.rename(topics="주제목록")
@app_commands.describe(topics="쉼표로 구분한 주제 목록")
async def topic_change_slash(interaction: discord.Interaction, topics: str):
    await _run_text_command_slash(interaction, f"/주제 변경 {topics}", ephemeral=True)


tree.add_command(news_group)
tree.add_command(topic_group)


@client.event
async def on_ready():
    global _slash_commands_synced, _voice_cleanup_task_started
    print(f"로그인됨: {client.user}")
    purge_expired_recordings()
    if not _voice_cleanup_task_started:
        asyncio.create_task(_voice_record_cleanup_loop())
        _voice_cleanup_task_started = True
    await restore_poll_tasks(client)
    start_daily_news_task(client)
    if not _slash_commands_synced:
        try:
            await tree.sync()
            _slash_commands_synced = True
        except Exception as e:
            print("Slash command sync error:", e)


@client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    await enforce_single_vote(client, payload)


@client.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    await refresh_poll_vote_count(client, payload)


@client.event
async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState,
):
    if client.user and member.id == client.user.id:
        await handle_bot_voice_disconnect(member, after)


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    room_key = get_room_key(message)
    bot_was_mentioned = client.user and _message_mentions_user(message, client.user)
    raw_content = clean_discord_content(message)

    if not bot_was_mentioned and is_news_command_text(raw_content):
        await handle_news_command(
            message=message,
            user_text=raw_content,
            client=client,
        )
        return

    if bot_was_mentioned:
        room_data = get_room_data(room_key)
        user_text = clean_discord_content(
            message,
            bot_user_id=client.user.id,
            remove_bot_mention=True,
        )

        if not user_text:
            await message.channel.send("응, 불렀어?")
            return

        display_name = getattr(message.author, "display_name", message.author.name)
        user_data = get_user_data(message.author.id, display_name)

        await handle_mentioned_message(
            message=message,
            user_text=user_text,
            user_data=user_data,
            room_key=room_key,
            room_data=room_data,
            client=client,
        )
        return

    room_data = get_existing_room_data(room_key)
    if room_data is None:
        return

    if room_data.get("group_mode", False):
        content = clean_discord_content(message)
        if content and not is_command_text(content):
            record_room_user_message(
                message,
                room_key,
                room_data,
                content=content,
            )


if __name__ == "__main__":
    client.run(DISCORD_BOT_TOKEN)
