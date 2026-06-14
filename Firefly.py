import asyncio
import logging

import discord
from discord import app_commands

from firefly.attachments import read_text_attachments
from firefly.commands import handle_mentioned_message, handle_silent_group_memory_update
from firefly.config import DISCORD_BOT_TOKEN, SPECIAL_USER_ID
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
    format_recording_list,
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


async def _run_silent_group_memory_update(
    *,
    message: discord.Message,
    user_text: str,
    room_key: str,
) -> None:
    try:
        display_name = getattr(message.author, "display_name", message.author.name)
        user_data = get_user_data(message.author.id, display_name)
        room_data = get_room_data(room_key)
        await handle_silent_group_memory_update(
            message=message,
            user_text=user_text,
            user_data=user_data,
            room_key=room_key,
            room_data=room_data,
            client=client,
        )
    except Exception as exc:
        print("Silent group memory update error:", exc)


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

    text = "…그 명령어를 사용할 권한이 없어."
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


@tree.command(name="프로필", description="유저의 프로필 이미지, 이름, 호감도를 보여줘요.")
@app_commands.rename(target="유저")
@app_commands.describe(target="확인할 유저. 비워두면 내 프로필을 보여줘요.")
async def profile_slash(interaction: discord.Interaction, target: discord.User | None = None):
    user_text = f"/프로필 {_mention_text(target)}".strip()
    await _run_text_command_slash(
        interaction,
        user_text,
        mentions=[target] if target is not None else None,
        ephemeral=False,
    )


@tree.command(name="주사위", description="지정한 범위 안에서 숫자 하나를 뽑아요.")
@app_commands.rename(start="시작", end="끝")
@app_commands.describe(start="시작 숫자. 끝을 비우면 1부터 이 숫자까지 뽑아요.", end="끝 숫자")
async def dice_slash(interaction: discord.Interaction, start: int, end: int | None = None):
    user_text = f"/주사위 {start}" if end is None else f"/주사위 {start} {end}"
    await _run_text_command_slash(interaction, user_text)


@tree.command(name="팀나누기", description="참가자를 섞어서 균형 있게 팀으로 나눠요.")
@app_commands.rename(members="참가자", team_count="팀수", members_per_team="팀당인원")
@app_commands.describe(
    members="쉼표 또는 | 로 구분해요. 예: 철수, 영희, 민수, 수진",
    team_count="만들 팀 수. 팀당인원과 둘 중 하나만 입력해요.",
    members_per_team="한 팀당 인원. 팀수와 둘 중 하나만 입력해요.",
)
async def team_split_slash(
    interaction: discord.Interaction,
    members: str,
    team_count: int | None = None,
    members_per_team: int | None = None,
):
    if team_count is not None and members_per_team is not None:
        await interaction.response.send_message("…팀수와 팀당인원은 둘 중 하나만 적어줘.", ephemeral=True)
        return
    if team_count is None and members_per_team is None:
        await interaction.response.send_message("…팀수나 팀당인원 중 하나는 필요해.", ephemeral=True)
        return

    option = f"팀수={team_count}" if team_count is not None else f"팀당={members_per_team}"
    await _run_text_command_slash(interaction, f"/팀나누기 {option} | {members}")


@tree.command(name="실행", description="명령어를 먼저 실행하고 그 결과를 반영해 반디가 답해요.")
@app_commands.rename(command_text="명령어", prompt="프롬프트")
@app_commands.describe(
    command_text="먼저 실행할 명령어. 여러 개는 &&로 구분해요. 예: 주사위 1 6 && 프로필 @유저",
    prompt="명령어 결과를 반영해서 답할 요청",
)
async def command_adapter_slash(
    interaction: discord.Interaction,
    command_text: str,
    prompt: str,
):
    separator = "||" if "|" in command_text else "|"
    await _run_text_command_slash(interaction, f"/실행 {command_text} {separator} {prompt}")


@tree.command(name="검색실행", description="이 답변 한 번만 인터넷 검색을 사용해 반디가 답해요. 권한 필요.")
@app_commands.rename(prompt="프롬프트", command_text="명령어")
@app_commands.describe(
    prompt="인터넷 검색을 사용해서 답할 요청",
    command_text="선택: 먼저 실행할 명령어. 여러 개는 &&로 구분해요.",
)
async def web_command_adapter_slash(
    interaction: discord.Interaction,
    prompt: str,
    command_text: str | None = None,
):
    if command_text:
        separator = "||" if "|" in command_text else "|"
        user_text = f"/검색실행 {command_text} {separator} {prompt}"
    else:
        user_text = f"/검색실행 {prompt}"
    await _run_text_command_slash(interaction, user_text)


@tree.command(name="추론", description="이 방의 OpenAI 추론 단계를 보거나 바꿔요. 권한 필요.")
@app_commands.rename(value="단계")
@app_commands.describe(value="비우면 현재 단계. 없음, 낮음, 보통, 높음 중 하나를 선택해요.")
@app_commands.choices(
    value=[
        app_commands.Choice(name="없음", value="none"),
        app_commands.Choice(name="낮음", value="low"),
        app_commands.Choice(name="보통", value="medium"),
        app_commands.Choice(name="높음", value="high"),
    ]
)
async def reasoning_slash(
    interaction: discord.Interaction,
    value: str | None = None,
):
    user_text = f"/추론 {value}" if value else "/추론"
    await _run_text_command_slash(interaction, user_text, ephemeral=True)


@tree.command(name="뇌", description="반디의 사용자 단기/장기 기억을 보여줘요. 권한 필요.")
@app_commands.rename(target="유저")
@app_commands.describe(target="확인할 유저")
async def brain_slash(interaction: discord.Interaction, target: discord.User):
    user_text = f"/뇌 {_mention_text(target)}".strip()
    await _run_text_command_slash(
        interaction,
        user_text,
        mentions=[target] if target is not None else None,
        ephemeral=True,
    )


@tree.command(name="뇌추가", description="반디의 사용자 단기 기억 후보를 추가해요. 권한 필요.")
@app_commands.rename(note="내용", target="유저")
@app_commands.describe(note="추가할 평가", target="대상 유저")
async def brain_add_slash(
    interaction: discord.Interaction,
    note: str,
    target: discord.User,
):
    user_text = f"/뇌추가 {_mention_text(target)} {note}".strip()
    await _run_text_command_slash(
        interaction,
        user_text,
        mentions=[target] if target is not None else None,
        ephemeral=True,
    )


@tree.command(name="뇌수정", description="반디의 사용자 장기 기억을 수정해요. 권한 필요.")
@app_commands.rename(index="번호", note="내용", target="유저")
@app_commands.describe(index="수정할 평가 번호", note="새 평가 내용", target="대상 유저")
async def brain_update_slash(
    interaction: discord.Interaction,
    index: int,
    note: str,
    target: discord.User,
):
    user_text = f"/뇌수정 {_mention_text(target)} {index} {note}".strip()
    await _run_text_command_slash(
        interaction,
        user_text,
        mentions=[target] if target is not None else None,
        ephemeral=True,
    )


@tree.command(name="뇌삭제", description="반디의 사용자 기억을 삭제해요. 권한 필요.")
@app_commands.rename(index="번호", target="유저")
@app_commands.describe(index="삭제할 장기 번호, 단기 후보 S번호, 또는 단기", target="대상 유저")
async def brain_delete_slash(
    interaction: discord.Interaction,
    index: str,
    target: discord.User,
):
    user_text = f"/뇌삭제 {_mention_text(target)} {index}".strip()
    await _run_text_command_slash(
        interaction,
        user_text,
        mentions=[target] if target is not None else None,
        ephemeral=True,
    )


@tree.command(name="역할", description="역할 부여, 제거, 색, 이름, 권한을 바꿔요. 권한 필요.")
@app_commands.rename(command_text="명령")
@app_commands.describe(command_text="예: 부여 @유저 @역할, 색 @역할 #ffaa00, 권한제거 @역할 관리자")
async def role_slash(interaction: discord.Interaction, command_text: str):
    await _run_text_command_slash(interaction, f"/역할 {command_text}", ephemeral=True)


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


@tree.command(name="녹음검색", description="저장된 통화 기록에서 질문이나 키워드로 필요한 내용을 찾아요.")
@app_commands.rename(query="질문")
@app_commands.describe(query="예: 어떤 사람이 한 말 찾아줘")
async def voice_search_slash(interaction: discord.Interaction, query: str):
    await _run_text_command_slash(interaction, f"/녹음검색 {query}", ephemeral=True)


@tree.command(name="봇상태", description="메모리, 뉴스, 투표, 통화 기록 상태를 확인해요. 권한 필요.")
async def bot_status_slash(interaction: discord.Interaction):
    await _run_text_command_slash(interaction, "/봇상태", ephemeral=True)


@tree.command(name="관리상태", description="메모리, 뉴스, 투표, 통화 기록 상태를 확인해요. 권한 필요.")
async def admin_status_slash(interaction: discord.Interaction):
    await _run_text_command_slash(interaction, "/관리상태", ephemeral=True)


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


@tree.command(name="메모리파일", description="대화/방/투표/뉴스 메모리 파일 또는 통화 기록 원본 파일을 받아와요.")
@app_commands.rename(filename="파일이름")
@app_commands.describe(filename="대화, 방, 투표, 뉴스, 메모리 파일명, 또는 통화 기록 파일명")
async def memory_file_slash(interaction: discord.Interaction, filename: str | None = None):
    user_text = f"/메모리파일 {filename or ''}".strip()
    await _run_text_command_slash(interaction, user_text, ephemeral=True)


@tree.command(name="memoryfile", description="메모리 JSON 파일을 받아와요. 권한 필요.")
@app_commands.rename(filename="파일이름")
@app_commands.describe(filename="대화, 방, 투표, 뉴스, 메모리 파일명, 또는 통화 기록 파일명")
async def memory_file_english_slash(interaction: discord.Interaction, filename: str | None = None):
    user_text = f"/memoryfile {filename or ''}".strip()
    await _run_text_command_slash(interaction, user_text, ephemeral=True)


@tree.command(name="메모리초기화", description="대화/방/투표/뉴스 메모리 파일 중 하나를 비워요. 권한 필요.")
@app_commands.rename(target="대상", confirm_text="확인문구")
@app_commands.describe(
    target="대화, 방, 투표, 뉴스 또는 conversation_memory.json 같은 파일 이름",
    confirm_text="정말 초기화하려면 확인이라고 입력",
)
async def memory_reset_slash(interaction: discord.Interaction, target: str, confirm_text: str):
    await _run_text_command_slash(
        interaction,
        f"/메모리초기화 {target} {confirm_text}",
        ephemeral=True,
    )


@tree.command(name="메모리파일초기화", description="대화/방/투표/뉴스 메모리 파일 중 하나를 비워요. 권한 필요.")
@app_commands.rename(target="대상", confirm_text="확인문구")
@app_commands.describe(
    target="대화, 방, 투표, 뉴스 또는 conversation_memory.json 같은 파일 이름",
    confirm_text="정말 초기화하려면 확인이라고 입력",
)
async def memory_file_reset_slash(interaction: discord.Interaction, target: str, confirm_text: str):
    await _run_text_command_slash(
        interaction,
        f"/메모리파일초기화 {target} {confirm_text}",
        ephemeral=True,
    )


@tree.command(name="유저정보", description="유저의 저장 정보와 최근 대화를 확인해요. 권한 필요.")
@app_commands.rename(target="유저")
@app_commands.describe(target="확인할 유저")
async def user_info_slash(interaction: discord.Interaction, target: discord.User):
    await _run_text_command_slash(
        interaction,
        f"/유저정보 {_mention_text(target)}",
        mentions=[target],
        ephemeral=True,
    )


@tree.command(name="호감도설정", description="유저의 호감도를 특정 값으로 맞춰요. 권한 필요.")
@app_commands.rename(target="유저", value="숫자")
@app_commands.describe(target="대상 유저", value="설정할 호감도")
async def set_affection_slash(interaction: discord.Interaction, target: discord.User, value: int):
    await _run_text_command_slash(
        interaction,
        f"/호감도설정 {_mention_text(target)} {value}",
        mentions=[target],
        ephemeral=True,
    )


@tree.command(name="호감도증감", description="유저의 호감도를 증감해요. 권한 필요.")
@app_commands.rename(target="유저", delta="숫자")
@app_commands.describe(target="대상 유저", delta="더하거나 뺄 값")
async def change_affection_slash(interaction: discord.Interaction, target: discord.User, delta: int):
    await _run_text_command_slash(
        interaction,
        f"/호감도증감 {_mention_text(target)} {delta}",
        mentions=[target],
        ephemeral=True,
    )


@tree.command(name="투표", description="투표를 만들어요. 권한 필요.")
@app_commands.rename(poll_text="내용")
@app_commands.describe(poll_text="예: 저녁 메뉴 | 항목수=3 | 치킨 | 피자 | 떡볶이 | 2주")
async def poll_slash(interaction: discord.Interaction, poll_text: str):
    await _run_text_command_slash(interaction, f"/투표 {poll_text}")


@tree.command(name="투표마감", description="진행 중인 투표를 마감해요. 권한 필요.")
@app_commands.rename(message_id="메시지id")
@app_commands.describe(message_id="생략하면 현재 채널의 유일한 진행 중 투표, 최근이면 최신 투표를 마감")
async def close_poll_slash(interaction: discord.Interaction, message_id: str | None = None):
    user_text = f"/투표마감 {message_id or ''}".strip()
    await _run_text_command_slash(interaction, user_text, ephemeral=True)


@tree.command(name="인터넷모드", description="이 방의 인터넷 검색 모드를 켜거나 꺼요. 권한 필요.")
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


@tree.command(name="단체모드", description="이 방의 단체 대화 기억 모드를 켜거나 꺼요. 권한 필요.")
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


@tree.command(name="방기억", description="현재 방의 단체 모드 기억을 보여줘요. 권한 필요.")
async def room_history_slash(interaction: discord.Interaction):
    await _run_text_command_slash(interaction, "/방기억", ephemeral=True)


@tree.command(name="방초기화", description="현재 방의 단체 기억을 비워요. 권한 필요.")
async def room_reset_slash(interaction: discord.Interaction):
    await _run_text_command_slash(interaction, "/방초기화", ephemeral=True)


@tree.command(name="방상태", description="현재 방의 인터넷/단체 모드 상태를 보여줘요. 권한 필요.")
async def room_status_slash(interaction: discord.Interaction):
    await _run_text_command_slash(interaction, "/방상태", ephemeral=True)


@news_group.command(name="받기", description="최신 소식 개인 메시지를 구독해요.")
@app_commands.rename(target="유저")
@app_commands.describe(target="관리 권한이 있으면 다른 사람을 지정할 수 있어요.")
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
@app_commands.describe(target="관리 권한이 있으면 다른 사람을 지정할 수 있어요.")
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


@news_group.command(name="시간", description="최신 소식 발송 시간을 보거나 바꿔요. 변경은 권한 필요.")
@app_commands.rename(time_text="시간")
@app_commands.describe(time_text="예: 09:00, 오전 9시. 비워두면 현재 시간을 보여줘요.")
async def news_time_slash(interaction: discord.Interaction, time_text: str | None = None):
    user_text = f"/최신 소식 시간 {time_text or ''}".strip()
    await _run_text_command_slash(interaction, user_text, ephemeral=True)


@news_group.command(name="중복초기화", description="이미 보낸 최신 소식 기록을 비워요. 권한 필요.")
@app_commands.rename(confirm_text="확인문구")
@app_commands.describe(confirm_text="정말 비우려면 확인이라고 입력")
async def news_history_reset_slash(interaction: discord.Interaction, confirm_text: str):
    await _run_text_command_slash(interaction, f"/최신 소식 중복초기화 {confirm_text}", ephemeral=True)


@news_group.command(name="중복삭제", description="이미 보낸 최신 소식 기록을 비워요. 권한 필요.")
@app_commands.rename(confirm_text="확인문구")
@app_commands.describe(confirm_text="정말 비우려면 확인이라고 입력")
async def news_history_delete_slash(interaction: discord.Interaction, confirm_text: str):
    await _run_text_command_slash(interaction, f"/최신 소식 중복삭제 {confirm_text}", ephemeral=True)


@news_group.command(name="기록초기화", description="이미 보낸 최신 소식 기록을 비워요. 권한 필요.")
@app_commands.rename(confirm_text="확인문구")
@app_commands.describe(confirm_text="정말 비우려면 확인이라고 입력")
async def news_record_reset_slash(interaction: discord.Interaction, confirm_text: str):
    await _run_text_command_slash(interaction, f"/최신 소식 기록초기화 {confirm_text}", ephemeral=True)


@news_group.command(name="중복기록초기화", description="이미 보낸 최신 소식 기록을 비워요. 권한 필요.")
@app_commands.rename(confirm_text="확인문구")
@app_commands.describe(confirm_text="정말 비우려면 확인이라고 입력")
async def news_duplicate_record_reset_slash(interaction: discord.Interaction, confirm_text: str):
    await _run_text_command_slash(interaction, f"/최신 소식 중복기록초기화 {confirm_text}", ephemeral=True)


@topic_group.command(name="목록", description="최신 소식 주제를 보여줘요.")
async def topic_list_slash(interaction: discord.Interaction):
    await _run_text_command_slash(interaction, "/주제 목록", ephemeral=True)


@topic_group.command(name="추가", description="최신 소식 주제를 추가해요. 권한 필요.")
@app_commands.rename(topic="주제")
@app_commands.describe(topic="추가할 주제")
async def topic_add_slash(interaction: discord.Interaction, topic: str):
    await _run_text_command_slash(interaction, f"/주제 추가 {topic}", ephemeral=True)


@topic_group.command(name="제거", description="최신 소식 주제를 제거해요. 권한 필요.")
@app_commands.rename(topic="주제")
@app_commands.describe(topic="제거할 주제")
async def topic_remove_slash(interaction: discord.Interaction, topic: str):
    await _run_text_command_slash(interaction, f"/주제 제거 {topic}", ephemeral=True)


@topic_group.command(name="설정", description="최신 소식 주제 목록을 새로 설정해요. 권한 필요.")
@app_commands.rename(topics="주제목록")
@app_commands.describe(topics="쉼표로 구분한 주제 목록")
async def topic_set_slash(interaction: discord.Interaction, topics: str):
    await _run_text_command_slash(interaction, f"/주제 설정 {topics}", ephemeral=True)


@topic_group.command(name="변경", description="최신 소식 주제 목록을 새로 변경해요. 권한 필요.")
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
        attachment_context = await read_text_attachments(getattr(message, "attachments", []))

        if not user_text and attachment_context:
            user_text = "첨부 파일을 읽어줘."

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
            attachment_context=attachment_context,
        )
        return

    room_data = get_existing_room_data(room_key)
    if room_data is None:
        return

    if room_data.get("group_mode", False):
        content = clean_discord_content(message)
        if content and not is_command_text(content):
            recorded = record_room_user_message(
                message,
                room_key,
                room_data,
                content=content,
            )
            if recorded and message.author.id == SPECIAL_USER_ID:
                asyncio.create_task(_run_silent_group_memory_update(
                    message=message,
                    user_text=content,
                    room_key=room_key,
                ))


if __name__ == "__main__":
    client.run(DISCORD_BOT_TOKEN)
