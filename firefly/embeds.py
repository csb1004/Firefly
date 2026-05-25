import discord

from .affection import get_affection_stage_label
from .config import DEFAULT_AFFECTION
from .text_utils import clamp_text, is_command_text


POLL_HELP_TEXT = (
    "`/투표 제목 | 선택지개수 | 선택지1 | 선택지2 | 마감`\n"
    "마감 예: `10분`, `2시간`, `23:30`, `2026-05-07 23:30`"
)
TEAM_HELP_TEXT = (
    "`/팀나누기 팀수=2 | 철수, 영희, 민수, 수진`\n"
    "`/팀나누기 팀당=3 | 철수 | 영희 | 민수 | 수진 | 지훈`"
)


def _avatar_url(user: discord.User | discord.Member) -> str | None:
    avatar = getattr(user, "display_avatar", None)
    return str(getattr(avatar, "url", "") or "") or None


def create_help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="반디 봇 도움말",
        description="사용 가능한 명령어 목록이야.",
        color=0x00FFFF,
    )

    fields = [
        ("/도움말", "명령어 목록과 사용 방법을 보여줘."),
        ("/호감도", "현재 너에 대한 반디의 호감도를 확인해."),
        ("/초기화", "최근 개인 대화 기억을 비워."),
        ("/호칭 [이름]", "반디가 너를 부를 호칭을 바꿔."),
        ("/프로필 [@유저]", "프로필 이미지, 이름, 호감도를 보여줘."),
        ("/주사위 [시작] [끝]", "범위 안에서 숫자 하나를 뽑아."),
        ("/팀나누기", TEAM_HELP_TEXT),
        ("/실행 [명령어] | [프롬프트]", "명령어 결과를 먼저 보여주고 그 결과를 반영해 답해."),
        ("/요약 [개인/방] [개수]", "최근 개인 대화나 방 대화를 요약해."),
        ("/최신소식 [받기/그만/상태]", "기술 소식 개인 메시지 구독을 관리해."),
        ("/주제 목록", "최신 소식 주제를 확인해."),
        ("그 긴거 해줘", "등록된 긴 문장을 그대로 출력해."),
    ]

    for name, value in fields:
        embed.add_field(name=name, value=value, inline=False)

    embed.set_footer(text="반디 봇")
    return embed


def create_special_help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="반디 봇 도움말",
        description="특별 사용자 전용 명령어까지 포함한 목록이야.",
        color=0x00FFFF,
    )

    fields = [
        (
            "기본",
            "`/도움말`, `/호감도`, `/초기화`, `/호칭 [이름]`, `/프로필 [@유저]`, `/요약 [개인/방] [개수]`",
        ),
        (
            "도구",
            "`/주사위 1 6`, `/실행 주사위 1 6 | 나온 숫자에 4 더해줘`\n"
            f"{TEAM_HELP_TEXT}",
        ),
        (
            "통화 기록",
            "`/기록`, `/기록중지`, `/대화목록`, `/요약 [파일명/1번/#1]`\n"
            "`/기록검색 [파일명] 질문`, `/녹음검색 [파일명] 질문`\n"
            "파일명 자리에는 `1번`, `#1`, `index:1`도 쓸 수 있어.",
        ),
        (
            "투표",
            f"`/투표`, `/투표마감 [메시지ID]`\n{POLL_HELP_TEXT}",
        ),
        (
            "뉴스",
            "`/최신소식 받기`, `/최신소식 그만`, `/최신소식 상태`, `/최신소식 목록`, `/최신소식 시간 [HH:MM]`\n"
            "`/최신소식 중복초기화 확인`, `/최신소식 중복삭제 확인`, `/최신소식 기록초기화 확인`, `/최신소식 중복기록초기화 확인`",
        ),
        (
            "뉴스 주제",
            "`/주제 목록`, `/주제 추가 [주제]`, `/주제 제거 [주제]`, `/주제 설정 [목록]`, `/주제 변경 [목록]`",
        ),
        (
            "유저 관리",
            "`/유저정보 @유저`, `/호감도설정 @유저 [숫자]`, `/호감도증감 @유저 [숫자]`",
        ),
        (
            "메모리",
            "`/메모리파일 [파일명]`, `/메모리초기화 확인`, `/메모리파일초기화 확인`",
        ),
        (
            "방/봇 관리",
            "`/인터넷모드 [on/off]`, `/단체모드 [on/off]`, `/방상태`, `/방기억`, `/방초기화`\n"
            "`/봇상태`, `/관리상태`",
        ),
    ]

    for name, value in fields:
        embed.add_field(name=name, value=value, inline=False)

    embed.set_footer(text="다른 사람에게는 비밀이어야 해.")
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
        speaker = item.get("speaker", "알 수 없음")
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
    embed.add_field(name="마지막 대화", value=last_seen, inline=False)
    avatar_url = _avatar_url(target_user)
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)

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
                delta_text = f" (호감도 {before} -> {after}, {sign}{delta})"

            history_lines.append(f"{i}. [반디] {content}{delta_text}")
        else:
            history_lines.append(f"{i}. [{role}] {content}")

    history_text = "\n".join(history_lines) if history_lines else "최근 대화 기록이 없어."
    embed.add_field(name="최근 대화", value=clamp_text(history_text, 1024, "\n..."), inline=False)
    embed.set_footer(text="반디 봇")
    return embed


def create_profile_embed(target_user: discord.User | discord.Member, user_data: dict) -> discord.Embed:
    display_name = getattr(target_user, "display_name", getattr(target_user, "name", "알 수 없음"))
    username = getattr(target_user, "name", display_name)
    mention = getattr(target_user, "mention", str(display_name))
    nickname = user_data.get("nickname", "없음")
    affection = int(user_data.get("affection", DEFAULT_AFFECTION))
    stage_text = get_affection_stage_label(affection)
    last_seen = user_data.get("last_seen") or "기록 없음"

    embed = discord.Embed(
        title=f"{display_name} 프로필",
        description=str(mention),
        color=0x00FFFF,
    )
    avatar_url = _avatar_url(target_user)
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)

    embed.add_field(name="이름", value=str(username), inline=True)
    embed.add_field(name="호칭", value=str(nickname), inline=True)
    embed.add_field(name="호감도", value=f"{affection} ({stage_text})", inline=True)
    embed.add_field(name="마지막 대화", value=str(last_seen), inline=False)
    embed.set_footer(text=f"사용자 ID: {getattr(target_user, 'id', '알 수 없음')}")
    return embed


def create_summary_embed(title: str, summary: str, used_count: int) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=clamp_text(summary.strip(), 3900, "\n..."),
        color=0x00FFFF,
    )
    embed.set_footer(text=f"요약에 사용한 메시지: {used_count}개 · 명령어 제외")
    return embed
