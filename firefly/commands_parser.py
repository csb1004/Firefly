from .command_registry import registered_special_only_prefixes
from .config import SUMMARY_DEFAULT_LIMIT


def matches_command(user_text: str, command: str) -> bool:
    return user_text == command or user_text.startswith(f"{command} ")


SPECIAL_ONLY_COMMAND_PREFIXES = (
    "/메모리파일",
    "/메모리 파일",
    "/memoryfile",
    "/메모리초기화",
    "/메모리파일초기화",
    "/유저정보",
    "/호감도설정",
    "/호감도증감",
    "/추론설정",
    "/추론",
    "/뇌추가",
    "/뇌수정",
    "/뇌삭제",
    "/뇌",
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
