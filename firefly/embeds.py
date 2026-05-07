import discord

from .affection import get_affection_stage_label
from .config import DEFAULT_AFFECTION
from .polls import POLL_COMMAND_EXAMPLE, POLL_COMMAND_FORMAT, POLL_DEADLINE_HELP
from .text_utils import clamp_text, is_command_text


def create_help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="반디 봇 도움말",
        description="명령어 목록과 사용 방법이야.",
        color=0x00FFFF,
    )

    fields = [
        ("/도움말", "명령어 목록과 사용 방법을 보여줘."),
        ("/호감도", "현재 너에 대한 호감도를 확인해."),
        ("/초기화", "최근 대화 기억을 비워."),
        ("/호칭 [이름]", "너를 부를 호칭을 바꿔.\n예: `/호칭 민서야`"),
        ("/요약 [개인/방] [개수]", "최근 대화를 요약해. 단체 모드에서는 방 대화도 요약할 수 있어."),
        ("그 긴거 해줘", "샘의 긴 대사를 그대로 출력해."),
    ]

    for name, value in fields:
        embed.add_field(name=name, value=value, inline=False)

    embed.set_footer(text="반디 봇")
    return embed


def create_special_help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="반디 봇 도움말",
        description="…너만 볼 수 있는 기능들도 같이 적어둘게.",
        color=0x00FFFF,
    )

    fields = [
        ("/도움말", "명령어 목록과 사용 방법을 보여줘."),
        ("/호감도", "현재 너에 대한 호감도를 확인해.\n너는 항상 1004로 고정돼."),
        ("/초기화", "최근 대화 기억을 비워."),
        ("/호칭 [이름]", "일반 사용자만 호칭을 바꿀 수 있어.\n너는 고정 호칭이라 바뀌지 않아."),
        (
            "/투표 제목 | 항목수 | 항목... | 마감",
            f"특별 사용자 전용 반응 투표를 열어.\n형식: {POLL_COMMAND_FORMAT}\n예: {POLL_COMMAND_EXAMPLE}\n{POLL_DEADLINE_HELP}",
        ),
        ("/요약 [개인/방] [개수]", "명령어를 제외하고 최근 대화를 요약해."),
        ("그 긴거 해줘", "샘의 긴 대사를 그대로 출력해."),
        ("/호감도설정 @유저 [숫자]", "특정 사용자의 호감도를 원하는 값으로 설정해.\n예: `/호감도설정 @개척자 75`"),
        ("/호감도증감 @유저 [숫자]", "특정 사용자의 호감도를 올리거나 내려.\n예: `/호감도증감 @개척자 -10`"),
        ("/메모리파일", "현재 저장된 memory.json 파일을 받아와."),
        ("/유저정보 @유저", "특정 사용자의 정보를 확인해."),
        ("/인터넷모드 [on/off]", "현재 방의 인터넷 검색 모드를 켜거나 꺼."),
        ("/단체모드 [on/off]", "현재 방의 단체 모드를 켜거나 꺼."),
        ("/방기억", "현재 방의 단체 모드 기억을 확인해."),
        ("/방초기화", "현재 방의 단체 기억만 비워."),
        ("/방상태", "현재 방의 인터넷 검색 모드 / 단체 모드 상태를 확인해."),
    ]

    for name, value in fields:
        embed.add_field(name=name, value=value, inline=False)

    embed.set_footer(text="…다른 사람에겐 비밀이야.")
    return embed


def create_room_history_embed(message: discord.Message, room_data: dict) -> discord.Embed:
    embed = discord.Embed(
        title="방 기억",
        description="현재 방의 단체 모드 기억이야.",
        color=0x00FFFF,
    )

    internet_mode = room_data.get("internet_mode", False)
    group_mode = room_data.get("group_mode", False)
    history = room_data.get("history", [])

    embed.add_field(name="인터넷 검색 모드", value="on" if internet_mode else "off", inline=False)
    embed.add_field(name="단체 모드", value="on" if group_mode else "off", inline=False)

    lines = []
    for i, item in enumerate(history[-8:], start=1):
        speaker = item.get("speaker", "누군가")
        role = item.get("role", "unknown")
        content = item.get("content", "").replace("```", "'''").strip()
        nickname = item.get("nickname")
        affection = item.get("affection")

        if not content or is_command_text(content):
            continue

        content = clamp_text(content, 93)

        if role == "user":
            extra = []
            if nickname:
                extra.append(f"호칭={nickname}")
            if affection is not None:
                extra.append(f"호감도={affection}")

            extra_text = f" ({', '.join(extra)})" if extra else ""
            lines.append(f"{i}. [{speaker}{extra_text}] {content}")
        elif role == "assistant":
            lines.append(f"{i}. [반디] {content}")
        else:
            lines.append(f"{i}. [{speaker}] {content}")

    history_text = "\n".join(lines) if lines else "이 방에 저장된 단체 기억이 없어."
    history_text = clamp_text(history_text, 1024, "\n...")
    embed.add_field(name="최근 방 대화", value=history_text, inline=False)

    channel_name = getattr(message.channel, "name", "DM")
    embed.set_footer(text=f"{channel_name} · 반디 봇")
    return embed


def create_user_info_embed(target_user: discord.User | discord.Member, user_data: dict) -> discord.Embed:
    embed = discord.Embed(
        title="유저 정보",
        description=f"{target_user.mention}의 현재 상태야.",
        color=0x00FFFF,
    )

    name = user_data.get("name", "없음")
    nickname = user_data.get("nickname", "없음")
    affection = int(user_data.get("affection", DEFAULT_AFFECTION))
    history = user_data.get("history", [])
    last_seen = user_data.get("last_seen") or "기록 없음"
    stage_text = get_affection_stage_label(affection)

    embed.add_field(name="이름", value=str(name), inline=False)
    embed.add_field(name="호칭", value=str(nickname), inline=False)
    embed.add_field(name="호감도", value=f"{affection} ({stage_text})", inline=False)
    embed.add_field(name="마지막 접속", value=last_seen, inline=False)

    history_lines = []
    for i, item in enumerate(history[-5:], start=1):
        role = item.get("role", "unknown")
        content = item.get("content", "").replace("```", "'''").strip()

        if not content or is_command_text(content):
            continue

        content = clamp_text(content, 103)

        if role == "user":
            history_lines.append(f"{i}. [사용자] {content}")
        elif role == "assistant":
            before = item.get("affection_before")
            delta = item.get("affection_delta")
            after = item.get("affection_after")

            delta_text = ""
            if delta is not None:
                sign = "+" if delta >= 0 else ""
                delta_text = f" (호감도: {before} → {after}, {sign}{delta})"

            history_lines.append(f"{i}. [반디] {content}{delta_text}")
        else:
            history_lines.append(f"{i}. [{role}] {content}")

    history_text = "\n".join(history_lines) if history_lines else "최근 대화 기록이 없어."
    embed.add_field(name="최근 대화", value=clamp_text(history_text, 1024, "\n..."), inline=False)
    embed.set_footer(text="반디 봇")
    return embed


def create_summary_embed(title: str, summary: str, used_count: int) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=clamp_text(summary.strip(), 3900, "\n..."),
        color=0x00FFFF,
    )
    embed.set_footer(text=f"요약에 사용한 메시지: {used_count}개 · 명령어 제외")
    return embed
