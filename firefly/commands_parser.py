import re

from .command_registry import registered_special_only_prefixes
from .config import SUMMARY_DEFAULT_LIMIT


def matches_command(user_text: str, command: str) -> bool:
    return user_text == command or user_text.startswith(f"{command} ")


SPECIAL_ONLY_COMMAND_PREFIXES = (
    "/기록",
    "/기록중지",
    "/대화목록",
    "/메모리파일",
    "/메모리초기화",
    "/메모리파일초기화",
    "/유저정보",
    "/호감도설정",
    "/호감도증감",
    "/투표마감",
    "/투표",
    "/검색실행",
    "/인터넷실행",
    "/검색답변",
    "/인터넷모드",
    "/단체모드",
    "/방기억",
    "/방초기화",
    "/방상태",
    "/최신 소식 시간",
    "/최신 소식 목록",
    "/최신 소식 상태",
    "/최신 소식 중복초기화",
    "/최신 소식 중복삭제",
    "/최신 소식 기록초기화",
    "/최신 소식 중복기록초기화",
    "/주제 추가",
    "/주제 제거",
    "/주제 설정",
    "/주제 변경",
)
SPECIAL_ONLY_COMMAND_PREFIXES = SPECIAL_ONLY_COMMAND_PREFIXES + registered_special_only_prefixes()

ROOM_SUMMARY_SCOPE_TOKENS = {"방", "단체", "채널", "room", "channel"}
USER_SUMMARY_SCOPE_TOKENS = {"개인", "나", "dm", "user"}
SUMMARY_SCOPE_TOKENS = ROOM_SUMMARY_SCOPE_TOKENS | USER_SUMMARY_SCOPE_TOKENS
SELF_TARGET_PATTERN = r"(?:나를|날|저를|절)"


def _clean_natural_text(user_text: str) -> str:
    text = re.sub(r"\s+", " ", user_text).strip()
    return text.rstrip(".!?。")


def _strip_polite_suffix(text: str) -> str:
    return re.sub(r"\s*(?:좀|제발)?\s*$", "", text).strip()


def _normalize_nickname_command(text: str) -> str | None:
    patterns = (
        rf"^(?:앞으로\s*)?{SELF_TARGET_PATTERN}\s+(.+?)(?:이라고|라고)\s*불러(?:줘|줄래|주세요)?$",
        r"^(?:앞으로\s*)?(.+?)(?:이라고|라고)\s*불러(?:줘|줄래|주세요)?$",
        r"^(?:호칭|칭호)(?:을|를|은|는)?\s+(.+?)(?:으로|로|이라고|라고)?\s*(?:바꿔|변경해|설정해)(?:줘|줄래|주세요)?$",
        r"^내\s*(?:호칭|칭호)(?:을|를|은|는)?\s+(.+?)(?:으로|로|이라고|라고)?\s*(?:바꿔|변경해|설정해)(?:줘|줄래|주세요)?$",
    )

    for pattern in patterns:
        match = re.fullmatch(pattern, text)
        if not match:
            continue

        nickname = _strip_polite_suffix(match.group(1))
        if nickname:
            return f"/호칭 {nickname}"
    return None


def _normalize_help_command(text: str) -> str | None:
    if "도움말" in text or ("명령어" in text and any(word in text for word in ("알려", "보여", "뭐", "목록"))):
        return "/도움말"
    return None


def _normalize_affection_command(text: str) -> str | None:
    if "호감도" in text and any(word in text for word in ("확인", "알려", "보여", "몇", "어때")):
        return "/호감도"
    return None


def _normalize_profile_command(text: str) -> str | None:
    if "프로필" not in text:
        return None

    mention = re.search(r"<@!?\d{15,25}>", text)
    if mention:
        return f"/프로필 {mention.group(0)}"
    if any(word in text for word in ("내", "나", "보여", "확인")):
        return "/프로필"
    return None


def _normalize_dice_command(text: str) -> str | None:
    if not any(word in text for word in ("주사위", "랜덤", "뽑아", "골라")):
        return None

    range_match = re.search(r"(\d+)\s*(?:부터|에서|~|-)\s*(\d+)", text)
    if range_match:
        return f"/주사위 {range_match.group(1)} {range_match.group(2)}"

    sides_match = re.search(r"(\d+)\s*(?:면체|까지)", text)
    if sides_match:
        return f"/주사위 1 {sides_match.group(1)}"

    if "주사위" in text:
        return "/주사위 1 6"
    return None


def _normalize_summary_command(text: str) -> str | None:
    if "요약" not in text:
        return None

    scope = None
    if any(word in text for word in ("방", "채널", "단체")):
        scope = "방"
    elif any(word in text for word in ("개인", "나랑", "나와", "우리")):
        scope = "개인"

    count_match = re.search(r"(\d+)\s*개", text)
    parts = ["/요약"]
    if scope:
        parts.append(scope)
    if count_match:
        parts.append(count_match.group(1))
    return " ".join(parts)


def _normalize_news_command(text: str) -> str | None:
    compact = text.replace(" ", "")
    if "최신소식" not in compact and "뉴스" not in compact and "소식" not in text:
        return None

    if "주제" in text:
        return "/주제 목록"
    if any(word in text for word in ("받고", "보내", "구독")) and not any(
        word in text for word in ("그만", "안", "해제", "취소")
    ):
        return "/최신소식 받기"
    if any(word in text for word in ("그만", "안 받을", "안받", "해제", "취소")):
        return "/최신소식 그만"
    if any(word in text for word in ("상태", "설정", "구독중", "구독 중")):
        return "/최신소식 상태"
    return None


def normalize_natural_command(user_text: str, *, special_user: bool = False) -> str | None:
    text = _clean_natural_text(user_text)
    if not text or text.startswith("/"):
        return None

    normalizers = (
        _normalize_nickname_command,
        _normalize_help_command,
        _normalize_affection_command,
        _normalize_profile_command,
        _normalize_dice_command,
        _normalize_summary_command,
        _normalize_news_command,
    )
    for normalizer in normalizers:
        command = normalizer(text)
        if command:
            return command

    return None


def is_special_only_command(user_text: str) -> bool:
    return any(matches_command(user_text, command) for command in SPECIAL_ONLY_COMMAND_PREFIXES)


def parse_summary_args(user_text: str, room_data: dict) -> tuple[str, int]:
    args = user_text.replace("/요약", "", 1).strip().split()
    scope = "room" if room_data.get("group_mode") else "user"
    limit = SUMMARY_DEFAULT_LIMIT

    for token in args:
        normalized = token.lower()
        if normalized in ROOM_SUMMARY_SCOPE_TOKENS:
            scope = "room"
        elif normalized in USER_SUMMARY_SCOPE_TOKENS:
            scope = "user"
        elif normalized.isdigit():
            limit = max(1, min(80, int(normalized)))

    return scope, limit


def command_arg(user_text: str, command: str) -> str:
    return user_text.replace(command, "", 1).strip()


def summary_recording_filename(user_text: str) -> str | None:
    arg = command_arg(user_text, "/요약")
    if not arg:
        return None

    first = arg.split()[0]
    if first.lower() in SUMMARY_SCOPE_TOKENS or first.isdigit():
        return None
    return first
