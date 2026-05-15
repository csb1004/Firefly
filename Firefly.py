import asyncio
import logging

import discord
from discord import app_commands

from firefly.ai import summarize_voice_recording
from firefly.commands import handle_mentioned_message
from firefly.config import DISCORD_BOT_TOKEN, MEMORY_FILE, SPECIAL_USER_ID
from firefly.embeds import create_summary_embed
from firefly.news import handle_news_command, is_news_command_text, start_daily_news_task
from firefly.polls import enforce_single_vote, refresh_poll_vote_count, restore_poll_tasks
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
    read_transcript_entries,
)

logging.getLogger("discord.ext.voice_recv.reader").setLevel(logging.WARNING)

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.voice_states = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
_slash_commands_synced = False
_voice_cleanup_task_started = False


def _message_mentions_user(message: discord.Message, user: object) -> bool:
    return any(getattr(mention, "id", None) == user.id for mention in message.mentions)


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


@tree.command(name="요약", description="저장된 통화 기록 파일을 요약해요.")
@app_commands.rename(filename="파일이름")
@app_commands.describe(filename="대화목록에 표시된 통화 기록 파일명")
async def recording_summary_slash(interaction: discord.Interaction, filename: str):
    if not await _require_special_interaction(interaction):
        return

    await interaction.response.defer(thinking=True, ephemeral=True)
    try:
        entries = read_transcript_entries(filename)
    except VoiceRecordNotFound:
        await interaction.followup.send("…그 이름의 통화 기록 파일을 찾지 못했어. `/대화목록`으로 확인해줘.", ephemeral=True)
        return

    summary, used_count = await summarize_voice_recording(entries, filename)
    await interaction.followup.send(
        embed=create_summary_embed(f"통화 기록 요약: {filename}", summary, used_count),
        ephemeral=True,
    )


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
