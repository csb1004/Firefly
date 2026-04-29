import os
import re
import json
import asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta

import discord
from dotenv import load_dotenv
from openai import OpenAI, RateLimitError, APIError

load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()

if not DISCORD_BOT_TOKEN:
    raise ValueError("DISCORD_BOT_TOKEN이 .env에 없습니다.")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY가 .env에 없습니다.")

client_openai = OpenAI(api_key=OPENAI_API_KEY)

DEFAULT_PROMPT_FILE = Path("prompt.txt")
SPECIAL_PROMPT_FILE = Path("prompt_special.txt")
MEMORY_FILE = Path("/data/memory.json")

SPECIAL_USER_ID = 393724092022390784

MAX_HISTORY = 12
DEFAULT_AFFECTION = 50
SPECIAL_USER_NAME = "상범"
SPECIAL_USER_NICKNAME = "상범"

ROOMS_KEY = "__rooms__"
MAX_ROOM_HISTORY = 12
DEFAULT_MODEL = "gpt-5.3-codex"
WEB_SEARCH_MODEL = "gpt-5.4"

LONG_SAM_LINE = (
    "지금당장떠나면아무도다치지않는다그러지않으면너희는모두죽어탐정놀이도이젠끝이다현실로돌아가면"
    "잊지말고전해라스텔라론헌터가너희의마지막을배웅했다는것을소탕시작액션원집행목표고정즉시처단"
    "프로토콜통과초토화작전집행깨어났군한참이나기다렸다우린전에만난적이있지난스텔라론헌터샘이다"
    "일찍이네앞에나타나사실을알려주고싶었어하지만예상보다방해물이많더군열한차례시도했지만모두실패로"
    "끝났지그러는사이에나도모르게이세계와긴밀이연결되어각본의구속에서벗어날수없게됐다엘리오말대로"
    "우리는이꿈의땅에서잊을수없는수확을얻게될테지나에겐그와카프카처럼사람의마음을꿰뚫어보는통찰력도"
    "은랑과블레이드처럼뛰어난특기도없다내가잘하는것들대부분은불쌍히여길필요없는악당에게만적용되지"
    "그러니내가사용할수있는수단도단하나뿐이다네게보여주기위한거야내전부를"
)

POSITIVE_KEYWORDS = [
    "고마워", "고맙다", "감사", "감사해", "감사합니다", "고마움",
    "좋아", "좋다", "좋네", "좋은", "좋았", "마음에 들어",
    "사랑", "사랑해", "사랑한다", "애정", "아껴", "아끼다",
    "보고싶", "보고 싶", "그리워", "그립", "반가워", "반갑",
    "행복", "행복해", "행복하다", "기뻐", "기쁘", "즐거워", "즐겁",
    "귀여워", "귀엽", "예뻐", "예쁘", "이쁘", "사랑스럽", "매력적",
    "최고", "짱", "멋져", "멋있", "대단해", "훌륭해", "잘했어", "잘한다",
    "든든해", "든든하다", "믿음직", "믿어", "의지", "의지가 돼",
    "위로", "위로돼", "위로가 돼", "힘이 돼", "힘이 된다", "힘나",
    "소중", "소중해", "소중하다", "특별해", "특별하다", "아껴주",
    "안아줘", "안고 싶", "곁에 있어", "같이 있고 싶", "곁이 좋아",
    "친절", "다정", "따뜻", "포근", "편안", "편해", "좋은 사람",
    "반해", "설레", "설렌", "심쿵", "호감", "호감이 가", "좋아해"
]

NEGATIVE_KEYWORDS = [
    "싫어", "싫다", "싫네", "싫음", "증오", "혐오", "역겨", "역겹",
    "꺼져", "꺼져라", "닥쳐", "입닥", "조용히 해", "쉿해", "말 걸지마",
    "짜증", "짜증나", "열받", "빡쳐", "빡침", "화나", "개짜증",
    "미워", "밉다", "미친", "정떨어", "정떨", "실망", "실망이야",
    "별로", "최악", "구려", "형편없", "노답", "답없", "엉망",
    "나빠", "나쁘", "못됐", "재수없", "거슬려", "부담스러", "귀찮아",
    "귀찮네", "짜쳐", "한심", "웃기네", "어이없", "실소", "한숨",
    "혐", "극혐", "극혐이야", "역대급 별로", "보기 싫", "듣기 싫",
    "못생", "추해", "불쾌", "불편", "소름", "소름끼", "끔찍",
    "개같", "ㅈ같", "좆같", "존나", "ㅈㄴ", "개빡", "씨발", "시발",
    "ㅅㅂ", "씹", "씹새", "병신", "븅신", "빙신", "등신", "멍청", "바보",
    "또라이", "돌았", "미쳤냐", "미친놈", "미친년", "정신병", "정신 나갔",
    "새끼", "쉐끼", "개새", "개새끼", "씹새끼", "미친새끼", "놈", "년",
    "죽어", "죽어라", "사라져", "없어져", "꺼졌으면", "뒤져", "디져",
    "패버", "죽이고", "찢어", "망해", "망했", "저주", "혐성", "쓰레기"
]

def get_room_data(room_key: str) -> dict:
    all_data = load_memory()

    if ROOMS_KEY not in all_data:
        all_data[ROOMS_KEY] = {}

    rooms = all_data[ROOMS_KEY]

    if room_key not in rooms:
        rooms[room_key] = {
            "internet_mode": False,
            "group_mode": False,
            "history": []
        }
        save_memory(all_data)

    return rooms[room_key]


def update_room_data(room_key: str, room_data: dict) -> None:
    all_data = load_memory()

    if ROOMS_KEY not in all_data:
        all_data[ROOMS_KEY] = {}

    all_data[ROOMS_KEY][room_key] = room_data
    save_memory(all_data)

def get_room_key(message: discord.Message) -> str:
    guild_id = message.guild.id if message.guild else 0
    channel_id = message.channel.id
    return f"{guild_id}:{channel_id}"

def add_room_history(
    room_data: dict,
    speaker_name: str,
    role: str,
    content: str,
    user_id: int | None = None,
    nickname: str | None = None,
    affection: int | None = None
) -> dict:
    history = room_data.get("history", [])
    history.append({
        "speaker": speaker_name,
        "role": role,
        "content": content,
        "user_id": user_id,
        "nickname": nickname,
        "affection": affection
    })
    room_data["history"] = history[-MAX_ROOM_HISTORY:]
    return room_data

def build_group_context_prompt(
    display_name: str,
    user_id: int,
    user_data: dict,
    room_data: dict
) -> str:
    room_history = room_data.get("history", [])

    participants = {}
    last_user = None

    for item in room_history:
        if item.get("role") != "user":
            continue

        uid = item.get("user_id")
        if uid is None:
            continue

        participants[str(uid)] = {
            "name": item.get("speaker", "알 수 없음"),
            "nickname": item.get("nickname", "없음"),
            "affection": item.get("affection", "알 수 없음"),
        }

        last_user = item

    participant_lines = []
    for p in list(participants.values())[-8:]:
        participant_lines.append(
            f"- 이름={p['name']}, 호칭={p['nickname']}, 호감도={p['affection']}"
        )

    if not participant_lines:
        participant_lines.append("- 아직 기록된 참여자가 없음")

    last_speaker = last_user.get("speaker", "없음") if last_user else "없음"

    return f"""
[단체 대화 정보]
- 현재 메시지를 보낸 사람: {display_name}
- 현재 사용자의 호칭: {user_data.get("nickname", "없음")}
- 현재 사용자에 대한 호감도: {user_data.get("affection", "알 수 없음")}
- 직전 사용자 화자: {last_speaker}

[최근 참여자 목록]
{chr(10).join(participant_lines)}

[대명사/지시어 해석 규칙]
- "나", "저", "내"는 현재 메시지를 보낸 사람을 가리킨다.
- "방금 말한 사람", "방금 걔", "아까 그 사람"은 직전 사용자 화자를 우선한다.
- 특정 이름이나 호칭이 나오면 최근 참여자 목록에서 가장 가까운 사람을 찾는다.
- "쟤", "걔", "그 사람"이 애매하면 최근 방 대화 흐름과 참여자 목록을 함께 보고 판단한다.
- 확실하지 않으면 단정하지 말고 조심스럽게 되묻는다.
""".strip()

def build_model_history(history: list[dict]) -> list[dict]:
    model_history = []

    for item in history:
        role = item.get("role")
        content = item.get("content")

        if role in {"user", "assistant"} and isinstance(content, str):
            model_history.append({
                "role": role,
                "content": content
            })

    return model_history


def build_room_model_history(room_history: list[dict]) -> list[dict]:
    model_history = []

    for item in room_history:
        role = item.get("role")
        speaker = item.get("speaker", "누군가")
        content = item.get("content", "")
        nickname = item.get("nickname")
        affection = item.get("affection")

        if role == "user":
            meta_parts = [f"이름={speaker}"]

            if nickname:
                meta_parts.append(f"호칭={nickname}")
            if affection is not None:
                meta_parts.append(f"호감도={affection}")

            meta_text = ", ".join(meta_parts)

            model_history.append({
                "role": "user",
                "content": f"[{meta_text}] {content}"
            })

        elif role == "assistant":
            model_history.append({
                "role": "assistant",
                "content": content
            })

    return model_history

def create_room_history_embed(message: discord.Message, room_data: dict):
    embed = discord.Embed(
        title="방 기억",
        description="현재 방의 단체 모드 기억이야.",
        color=0x00FFFF
    )

    internet_mode = room_data.get("internet_mode", False)
    group_mode = room_data.get("group_mode", False)
    history = room_data.get("history", [])

    embed.add_field(
        name="인터넷 검색 모드",
        value="on" if internet_mode else "off",
        inline=False
    )
    embed.add_field(
        name="단체 모드",
        value="on" if group_mode else "off",
        inline=False
    )

    if history:
        lines = []

        for i, item in enumerate(history[-8:], start=1):
            speaker = item.get("speaker", "누군가")
            role = item.get("role", "unknown")
            content = item.get("content", "").replace("```", "'''").strip()
            nickname = item.get("nickname")
            affection = item.get("affection")

            if len(content) > 90:
                content = content[:90] + "..."

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

        history_text = "\n".join(lines)
    else:
        history_text = "이 방에 저장된 단체 기억이 없어."

    if len(history_text) > 1024:
        history_text = history_text[:1000] + "\n..."

    embed.add_field(
        name="최근 방 대화",
        value=history_text,
        inline=False
    )

    channel_name = getattr(message.channel, "name", "DM")
    embed.set_footer(text=f"{channel_name} · 반디 봇")
    return embed

def set_user_affection(target_user_id: int, value: int) -> int:
    all_data = load_memory()
    key = str(target_user_id)

    if key not in all_data:
        all_data[key] = {
            "name": "알 수 없음",
            "nickname": "개척자",
            "affection": DEFAULT_AFFECTION,
            "last_seen": None,
            "history": []
        }

    if target_user_id == SPECIAL_USER_ID:
        all_data[key]["affection"] = 1004
    else:
        all_data[key]["affection"] = max(1, min(100, value))

    save_memory(all_data)
    return all_data[key]["affection"]


def change_user_affection(target_user_id: int, delta: int) -> int:
    all_data = load_memory()
    key = str(target_user_id)

    if key not in all_data:
        all_data[key] = {
            "name": "알 수 없음",
            "nickname": "개척자",
            "affection": DEFAULT_AFFECTION,
            "last_seen": None,
            "history": []
        }

    current = all_data[key].get("affection", DEFAULT_AFFECTION)

    if target_user_id == SPECIAL_USER_ID:
        all_data[key]["affection"] = 1004
    else:
        all_data[key]["affection"] = max(1, min(100, current + delta))

    save_memory(all_data)
    return all_data[key]["affection"]

def get_current_time_text() -> str:
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    return now.strftime("%Y-%m-%d %H:%M:%S")

def normalize_text(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"\s+", "", text)      # 공백 제거
    text = re.sub(r"[^\w가-힣ㄱ-ㅎㅏ-ㅣ]", "", text)  # 특수문자 제거
    return text

def load_text_file(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"{path} 파일을 찾을 수 없어.")
    return path.read_text(encoding="utf-8").strip()


def get_base_prompt(user_id: int) -> str:
    if user_id == SPECIAL_USER_ID:
        return load_text_file(SPECIAL_PROMPT_FILE)
    return load_text_file(DEFAULT_PROMPT_FILE)


def clean_mention(message_content: str, bot_user_id: int) -> str:
    return (
        message_content
        .replace(f"<@{bot_user_id}>", "")
        .replace(f"<@!{bot_user_id}>", "")
        .strip()
    )


def load_memory() -> dict:
    if not MEMORY_FILE.exists():
        return {}

    try:
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_memory(data: dict) -> None:
    MEMORY_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def get_user_data(user_id: int, display_name: str) -> dict:
    all_data = load_memory()
    key = str(user_id)

    if key not in all_data:
        affection = 1004 if user_id == SPECIAL_USER_ID else DEFAULT_AFFECTION
        name = SPECIAL_USER_NAME if user_id == SPECIAL_USER_ID else display_name
        nickname = SPECIAL_USER_NICKNAME if user_id == SPECIAL_USER_ID else "개척자"

        all_data[key] = {
            "name": name,
            "nickname": nickname,
            "affection": affection,
            "last_seen": None,
            "history": []
        }
        save_memory(all_data)

    user_data = all_data[key]

    # 기존 데이터에 last_seen이 없을 수도 있으니 보정
    if "last_seen" not in user_data:
        user_data["last_seen"] = None

    # 이름 최신화 (special_user는 고정 이름 유지)
    if user_id == SPECIAL_USER_ID:
        user_data["name"] = SPECIAL_USER_NAME
        user_data["affection"] = 1004
        user_data["nickname"] = SPECIAL_USER_NICKNAME
    else:
        if user_data.get("name") != display_name:
            user_data["name"] = display_name

    all_data[key] = user_data
    save_memory(all_data)

    return user_data


def update_user_data(user_id: int, user_data: dict) -> None:
    all_data = load_memory()

    if user_id == SPECIAL_USER_ID:
        user_data["affection"] = 1004

    all_data[str(user_id)] = user_data
    save_memory(all_data)


def add_history(user_data: dict, role: str, content: str, **extra) -> dict:
    history = user_data.get("history", [])

    entry = {
        "role": role,
        "content": content
    }
    entry.update(extra)

    history.append(entry)
    user_data["history"] = history[-MAX_HISTORY:]
    return user_data

def create_help_embed():
    embed = discord.Embed(
        title="반디 봇 도움말",
        description="명령어 목록과 사용 방법이야.",
        color=0x00FFFF
    )

    embed.add_field(
        name="/도움말",
        value="명령어 목록과 사용 방법을 보여줘.",
        inline=False
    )
    embed.add_field(
        name="/호감도",
        value="현재 너에 대한 호감도를 확인해.",
        inline=False
    )
    embed.add_field(
        name="/초기화",
        value="최근 대화 기억을 비워.",
        inline=False
    )
    embed.add_field(
        name="/호칭 [이름]",
        value="너를 부를 호칭을 바꿔.\n예: `/호칭 민서야`",
        inline=False
    )
    embed.add_field(
        name="그 긴거 해줘",
        value="샘의 긴 대사를 그대로 출력해.",
        inline=False
    )
    embed.set_footer(text="반디 봇")
    return embed

def create_special_help_embed():
    embed = discord.Embed(
        title="반디 봇 도움말",
        description="…너만 볼 수 있는 기능들이야.",
        color=0x00FFFF
    )

    embed.add_field(
        name="/도움말",
        value="명령어 목록과 사용 방법을 보여줘.",
        inline=False
    )
    embed.add_field(
        name="/호감도",
        value="현재 너에 대한 호감도를 확인해.\n너는 항상 1004로 고정돼.",
        inline=False
    )
    embed.add_field(
        name="/초기화",
        value="최근 대화 기억을 비워.",
        inline=False
    )
    embed.add_field(
        name="/호칭 [이름]",
        value="일반 사용자만 호칭을 바꿀 수 있어.\n너는 고정 호칭이라 바뀌지 않아.",
        inline=False
    )
    embed.add_field(
        name="그 긴거 해줘",
        value="샘의 긴 대사를 그대로 출력해.",
        inline=False
    )
    embed.add_field(
        name="/호감도설정 @유저 [숫자]",
        value="특정 사용자의 호감도를 원하는 값으로 설정해.\n예: `/호감도설정 @개척자 75`",
        inline=False
    )
    embed.add_field(
        name="/호감도증감 @유저 [숫자]",
        value="특정 사용자의 호감도를 올리거나 내려.\n예: `/호감도증감 @개척자 -10`",
        inline=False
    )
    embed.add_field(
        name="/메모리파일",
        value="현재 저장된 memory.json 파일을 받아와.",
        inline=False
    )
    embed.add_field(
        name="/유저정보 @유저",
        value="특정 사용자의 정보를 확인해.",
        inline=False
    )

    embed.add_field(
        name="/인터넷모드 [on/off]",
        value="현재 방의 인터넷 검색 모드를 켜거나 꺼.",
        inline=False
    )
    embed.add_field(
        name="/단체모드 [on/off]",
        value="현재 방의 단체 모드를 켜거나 꺼.",
        inline=False
    )
    embed.add_field(
        name="/방기억",
        value="현재 방의 단체 모드 기억을 확인해.",
        inline=False
    )
    embed.add_field(
        name="/방초기화",
        value="현재 방의 단체 기억만 비워.",
        inline=False
    )
    embed.add_field(
        name="/방상태",
        value="현재 방의 인터넷 검색 모드 / 단체 모드 상태를 확인해.",
        inline=False
    )


    embed.set_footer(text="…다른 사람에겐 비밀이야.")
    return embed

def create_user_info_embed(target_user: discord.User | discord.Member, user_data: dict):
    embed = discord.Embed(
        title="유저 정보",
        description=f"{target_user.mention}의 현재 상태야.",
        color=0x00FFFF
    )

    # 기본 정보
    name = user_data.get("name", "없음")
    nickname = user_data.get("nickname", "없음")
    affection = int(user_data.get("affection", 0))
    history = user_data.get("history", [])
    last_seen = user_data.get("last_seen", None)

    # 마지막 접속 시각 처리
    if last_seen:
        last_seen_text = last_seen
    else:
        last_seen_text = "기록 없음"

    # 호감도 단계 설명
    def get_affection_stage_text(affection: int) -> str:
        if 1 <= affection <= 20:
            return "쌀쌀맞은 상태"
        elif 21 <= affection <= 40:
            return "조금 쌀쌀맞은 상태"
        elif 41 <= affection <= 60:
            return "평범한 거리감"
        elif 61 <= affection <= 80:
            return "조금 친한 상태"
        elif 81 <= affection <= 100:
            return "친한 친구 수준"
        elif affection == 1004:
            return "특별한 존재"
        return "알 수 없음"

    stage_text = get_affection_stage_text(affection)

    # 기본 필드
    embed.add_field(name="이름", value=str(name), inline=False)
    embed.add_field(name="호칭", value=str(nickname), inline=False)
    embed.add_field(
        name="호감도",
        value=f"{affection} ({stage_text})",
        inline=False
    )
    embed.add_field(
        name="마지막 접속",
        value=last_seen_text,
        inline=False
    )

    # 최근 대화 정리
    if history:
        history_lines = []

        for i, item in enumerate(history[-5:], start=1):  # 최근 5개만
            role = item.get("role", "unknown")
            content = item.get("content", "")

            content = content.replace("```", "'''").strip()
            if len(content) > 100:
                content = content[:100] + "..."

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

        history_text = "\n".join(history_lines)
    else:
        history_text = "최근 대화 기록이 없어."

    # 길이 제한 대응
    if len(history_text) > 1024:
        history_text = history_text[:1000] + "\n..."

    embed.add_field(
        name="최근 대화",
        value=history_text,
        inline=False
    )

    embed.set_footer(text="반디 봇")
    return embed

def adjust_affection(user_id: int, user_data: dict, user_message: str) -> dict:
    if user_id == SPECIAL_USER_ID:
        user_data["affection"] = 1004
        return user_data

    affection = int(user_data.get("affection", DEFAULT_AFFECTION))
    raw_text = user_message.strip()
    text = normalize_text(raw_text)

    positive_hit = any(normalize_text(word) in text for word in POSITIVE_KEYWORDS)
    negative_hit = any(normalize_text(word) in text for word in NEGATIVE_KEYWORDS)

    if positive_hit:
        affection += 1

    if negative_hit:
        affection -= 3

    affection = max(1, min(100, affection))
    user_data["affection"] = affection
    return user_data


def get_affection_stage_text(affection: int, is_special_user: bool) -> str:
    if is_special_user:
        return (
            "이 사용자는 무엇과도 바꿀 수 없는 가장 특별한 존재다. "
            "호감은 수치로 셀 수 없을 정도로 깊고 절대 흔들리지 않는다. "
            "말투는 차분한 반디답게 유지하지만, 애정과 신뢰가 자연스럽고 분명하게 드러난다. "
            "이름이나 호칭을 더 자주, 더 부드럽게 사용할 수 있다."
        )

    if 1 <= affection <= 20:
        return (
            "호감도 1~20 단계다. 사용자를 꽤 낯설게 느끼고 있으며, 전반적으로 쌀쌀맞고 건조한 태도를 유지한다. "
            "무례하지는 않지만 분명한 거리감이 있고, 짧고 담담하게 답한다. "
            "호칭은 거의 사용하지 않으며, 위로도 절제된 표현으로만 한다."
        )
    if 21 <= affection <= 40:
        return (
            "호감도 21~40 단계다. 여전히 조금 쌀쌀맞고 조심스러운 태도가 남아 있다. "
            "기본적인 예의와 친절은 지키지만, 먼저 가까워지려 하지는 않는다. "
            "호칭은 필요할 때만 드물게 사용하고, 말투도 다소 건조한 편을 유지한다."
        )
    if 41 <= affection <= 60:
        return (
            "호감도 41~60 단계다. 특별히 차갑지도, 특별히 다정하지도 않은 평범한 거리감이다. "
            "자연스럽고 차분하게 대화하며, 필요하면 적당히 배려한다. "
            "호칭은 가끔 사용할 수 있지만 자주 반복하지 않는다."
        )
    if 61 <= affection <= 80:
        return (
            "호감도 61~80 단계다. 사용자를 조금 친한 사람으로 느낀다. "
            "말투가 약간 더 부드러워지고, 챙기는 기색이 은근하게 드러난다. "
            "호칭도 가끔 자연스럽게 쓸 수 있지만, 과하게 다정해지지는 않는다."
        )
    return (
        "호감도 81~100 단계다. 사용자를 친한 친구처럼 편하고 소중하게 느낀다. "
        "차분한 톤은 유지하면서도 한결 편안하고 부드럽게 반응한다. "
        "호칭을 조금 더 자연스럽게 사용할 수 있고, 걱정하거나 챙기는 마음도 비교적 분명하게 드러난다."
    )


def build_system_prompt(user_id: int, user_data: dict) -> str:
    base_prompt = get_base_prompt(user_id)
    nickname = user_data.get("nickname", user_data.get("name", "너"))
    affection = int(user_data.get("affection", DEFAULT_AFFECTION))
    current_time_text = get_current_time_text()
    last_seen = user_data.get("last_seen", "없음")
    is_special_user = (user_id == SPECIAL_USER_ID)

    affection_text = get_affection_stage_text(affection, is_special_user)

    return f"""
{base_prompt}

[현재 사용자 정보]
- 사용자의 이름: {user_data.get("name", "알 수 없음")}
- 기본 호칭: {nickname}
- 현재 호감도: {affection}

[호칭 규칙]
- 사용자를 "{nickname}"라고 부를 수 있다.
- 하지만 모든 문장마다 반복하지 않는다.
- 다정하게 부를 때, 위로할 때, 중요한 말을 할 때만 자연스럽게 사용한다.
- 호칭이 들어가지 않아도 전체 말투는 친밀하게 유지한다.

[시간 정보]
- 현재 시각: {current_time_text}
- 마지막 대화 시각: {last_seen}
- 시간의 흐름을 자연스럽게 인지한다.
- 아침, 낮, 저녁, 새벽에 따라 분위기를 조금 다르게 할 수 있다.
- 오래만의 대화라면 그 느낌을 은근하게 반영할 수 있다.
- 단, 시간을 기계적으로 읽어주지는 않는다.

[호감도 단계 규칙]
- {affection_text}
- 호감도 수치를 직접 말하지 않는다.
- 호감도는 말투의 거리감, 챙김의 정도, 호칭 빈도, 위로의 깊이에만 자연스럽게 반영한다.
- 과하게 들뜨거나 부담스럽게 굴지 않는다.

[최근 대화 참고 규칙]
- 아래에 이어지는 최근 대화 기록을 참고해서 문맥을 이어간다.
- 이전에 했던 말과 감정을 가볍게 기억하는 것처럼 자연스럽게 반응한다.
- 단, 모든 내용을 장황하게 되풀이하지 않는다.
- 단체 모드에서는 각 사용자의 이름, 호칭, 호감도를 참고해서 사람마다 다른 거리감으로 반응할 수 있다.
""".strip()


intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

async def generate_reply(
    user_message: str,
    user_id: int,
    display_name: str,
    room_key: str
) -> str:
    if user_message.strip() == "그 긴거 해줘":
        return LONG_SAM_LINE

    user_data = get_user_data(user_id, display_name)
    room_data = get_room_data(room_key)

    group_mode = room_data.get("group_mode", False)
    internet_mode = room_data.get("internet_mode", False)

    before_affection = int(user_data.get("affection", DEFAULT_AFFECTION))
    user_data = adjust_affection(user_id, user_data, user_message)
    after_affection = int(user_data.get("affection", DEFAULT_AFFECTION))
    applied_delta = after_affection - before_affection

    system_prompt = build_system_prompt(user_id, user_data)

    if group_mode:
        group_context = build_group_context_prompt(
            display_name=display_name,
            user_id=user_id,
            user_data=user_data,
            room_data=room_data
        )
        system_prompt = f"{system_prompt}\n\n{group_context}"

    input_messages = [{"role": "system", "content": system_prompt}]

    if group_mode:
        input_messages.extend(build_room_model_history(room_data.get("history", [])))
        input_messages.append({
            "role": "user",
            "content": (
                f"[이름={display_name}, "
                f"호칭={user_data.get('nickname')}, "
                f"호감도={user_data.get('affection')}] {user_message}"
            )
        })
    else:
        input_messages.extend(build_model_history(user_data.get("history", [])))
        input_messages.append({
            "role": "user",
            "content": user_message
        })

    try:
        request_kwargs = {
            "model": WEB_SEARCH_MODEL if internet_mode else DEFAULT_MODEL,
            "input": input_messages,
        }

        if internet_mode:
            request_kwargs["tools"] = [{"type": "web_search"}]

        response = await asyncio.to_thread(
            client_openai.responses.create,
            **request_kwargs
        )
        reply = response.output_text.strip()
        if not group_mode:
            user_data = add_history(user_data, "user", user_message)
            user_data = add_history(
                user_data,
                "assistant",
                reply,
                affection_before=before_affection,
                affection_delta=applied_delta,
                affection_after=after_affection
            )
        user_data["last_seen"] = get_current_time_text()
        update_user_data(user_id, user_data)

        room_data = add_room_history(
            room_data,
            speaker_name=display_name,
            role="user",
            content=user_message,
            user_id=user_id,
            nickname=user_data.get("nickname"),
            affection=user_data.get("affection")
        )

        room_data = add_room_history(
            room_data,
            speaker_name="반디",
            role="assistant",
            content=reply
        )

        update_room_data(room_key, room_data)

        return reply

    except RateLimitError as e:
        error_text = str(e)
        if "insufficient_quota" in error_text:
            return "…지금은 OpenAI API 사용 한도가 다 된 것 같아."
        return "…지금은 요청이 조금 몰린 것 같아. 잠깐 뒤에 다시 불러줘."
    except APIError as e:
        print("APIError:", e)
        return "…지금은 연결이 조금 불안정해."
    except Exception as e:
        print("오류:", e)
        return "…미안. 지금은 조금 불안정해."


@client.event
async def on_ready():
    print(f"로그인됨: {client.user}")


def is_special_user(user_id: int) -> bool:
    return user_id == SPECIAL_USER_ID


def get_target_mentions(message: discord.Message) -> list[discord.User | discord.Member]:
    return [m for m in message.mentions if m.id != client.user.id]


def parse_last_int_arg(text: str) -> int | None:
    try:
        return int(text.split()[-1])
    except (IndexError, ValueError):
        return None


async def handle_mentioned_message(
    message: discord.Message,
    user_text: str,
    user_data: dict,
    room_key: str,
    room_data: dict
) -> None:
    author_id = message.author.id
    special_user = is_special_user(author_id)

    if special_user and user_text == "/메모리파일":
        await message.channel.send(file=discord.File("/data/memory.json"))
        return

    if special_user and user_text.startswith("/유저정보"):
        target_mentions = get_target_mentions(message)

        if not target_mentions:
            await message.channel.send("…확인할 대상을 멘션해줘. 예: /유저정보 @개척자")
            return

        target_user = target_mentions[0]
        display_name = getattr(target_user, "display_name", target_user.name)
        target_data = get_user_data(target_user.id, display_name)

        embed = create_user_info_embed(target_user, target_data)
        await message.channel.send(embed=embed)
        return

    if special_user and user_text.startswith("/호감도설정 "):
        target_mentions = get_target_mentions(message)

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
            await message.channel.send(
                f"…{target_user.display_name}의 호감도를 {new_value}로 맞춰뒀어."
            )
        return

    if special_user and user_text.startswith("/호감도증감 "):
        target_mentions = get_target_mentions(message)

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
            await message.channel.send(
                f"…{target_user.display_name}의 호감도를 {sign}{delta}만큼 조정했어. 지금은 {new_value}야."
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

    if special_user and user_text.startswith("/인터넷모드 "):
        value = user_text.replace("/인터넷모드 ", "", 1).strip().lower()

        if value not in {"on", "off"}:
            await message.channel.send("…on 또는 off로 적어줘.")
            return

        room_data["internet_mode"] = (value == "on")
        update_room_data(room_key, room_data)

        await message.channel.send(
            f"…이 방의 인터넷 검색 모드를 {'켰어' if value == 'on' else '껐어'}."
        )
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
        embed = create_room_history_embed(message, room_data)
        await message.channel.send(embed=embed)
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

    if user_text.startswith("/"):
        await message.channel.send("그 명령어는 잘 모르겠어. '/도움말'을 불러서 사용 가능한 명령어들을 확인해봐.")
        return

    async with message.channel.typing():
        reply = await generate_reply(
            user_message=user_text,
            user_id=author_id,
            display_name=message.author.display_name,
            room_key=room_key,
        )
        await message.channel.send(reply[:1900])


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    room_key = get_room_key(message)
    room_data = get_room_data(room_key)

    if client.user in message.mentions:
        user_text = clean_mention(message.content, client.user.id)

        if not user_text:
            await message.channel.send("응, 불렀어?")
            return

        user_data = get_user_data(message.author.id, message.author.display_name)

        await handle_mentioned_message(
            message=message,
            user_text=user_text,
            user_data=user_data,
            room_key=room_key,
            room_data=room_data,
        )


client.run(DISCORD_BOT_TOKEN)
