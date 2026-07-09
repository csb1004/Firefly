from .brain import format_brain_notes
from .affection import get_affection_stage_text
from .config import (
    BANDI_LOREBOOK_FILE,
    COMMAND_GUIDE_FILE,
    DEFAULT_AFFECTION,
    MAX_MODEL_HISTORY,
    MAX_ROOM_MODEL_HISTORY,
    SPECIAL_COMMAND_GUIDE_FILE,
    SPECIAL_USER_ID,
)
from .emoticons import build_emoticon_prompt
from .text_utils import get_base_prompt, get_current_time_text, is_command_text, load_text_file

LOREBOOK_RUNTIME_START = "<!-- RUNTIME-START -->"
LOREBOOK_RUNTIME_END = "<!-- RUNTIME-END -->"


def _extract_lorebook_runtime(text: str) -> str:
    start_index = text.find(LOREBOOK_RUNTIME_START)
    end_index = text.find(LOREBOOK_RUNTIME_END)
    if start_index == -1 or end_index == -1 or end_index <= start_index:
        return text.strip()
    return text[start_index + len(LOREBOOK_RUNTIME_START):end_index].strip()


def load_bandi_lorebook_prompt() -> str:
    if not BANDI_LOREBOOK_FILE.exists():
        return ""
    return _extract_lorebook_runtime(BANDI_LOREBOOK_FILE.read_text(encoding="utf-8"))


def build_group_context_prompt(
    display_name: str,
    user_id: int,
    user_data: dict,
    room_data: dict,
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
            "user_id": uid,
            "name": item.get("speaker", "알 수 없음"),
            "nickname": item.get("nickname", "없음"),
            "affection": item.get("affection", "알 수 없음"),
        }
        last_user = item

    participant_lines = []
    for participant in list(participants.values())[-8:]:
        participant_lines.append(
            f"- ID={participant['user_id']}, 이름={participant['name']}, "
            f"호칭={participant['nickname']}, 호감도={participant['affection']}"
        )

    if not participant_lines:
        participant_lines.append("- 아직 기록된 참여자가 없음")

    last_speaker = last_user.get("speaker", "없음") if last_user else "없음"

    return f"""
[단체 대화 정보]
- 현재 메시지를 보낸 사람: {display_name}
- 현재 사용자의 호칭: {user_data.get("nickname", "없음")}
- 현재 사용자에 대한 호감도: {user_data.get("affection", "알 수 없음")}
- 직전 사용자 발화자: {last_speaker}

[최근 참여자 목록]
{chr(10).join(participant_lines)}

[대명사/지시어 해석 규칙]
- "나", "저", "내"는 현재 메시지를 보낸 사람을 가리킨다.
- "방금 말한 사람", "방금 걔", "아까 그 사람"은 직전 사용자 발화자를 우선한다.
- 특정 이름이나 호칭이 나오면 최근 참여자 목록에서 가장 가까운 사람을 찾는다.
- "그", "걔", "그 사람"이 애매하면 최근 발화 흐름과 참여자 목록을 함께 보고 판단한다.
- 확실하지 않으면 단정하지 말고 조심스럽게 물어본다.
""".strip()


def build_model_history(history: list[dict]) -> list[dict]:
    model_history = []

    for item in history[-MAX_MODEL_HISTORY:]:
        role = item.get("role")
        content = item.get("content")

        if (
            role in {"user", "assistant"}
            and isinstance(content, str)
            and not is_command_text(content)
        ):
            model_history.append({
                "role": role,
                "content": content,
            })

    return model_history


def build_room_model_history(room_history: list[dict]) -> list[dict]:
    model_history = []

    for item in room_history[-MAX_ROOM_MODEL_HISTORY:]:
        role = item.get("role")
        speaker = item.get("speaker", "누군가")
        content = item.get("content", "")
        nickname = item.get("nickname")
        affection = item.get("affection")

        if not isinstance(content, str) or is_command_text(content):
            continue

        if role == "user":
            meta_parts = [f"이름={speaker}"]

            if nickname:
                meta_parts.append(f"호칭={nickname}")
            if affection is not None:
                meta_parts.append(f"호감도={affection}")

            model_history.append({
                "role": "user",
                "content": f"[{', '.join(meta_parts)}] {content}",
            })

        elif role == "assistant":
            model_history.append({
                "role": "assistant",
                "content": content,
            })

    return model_history


def build_system_prompt(
    user_id: int,
    user_data: dict,
    *,
    include_command_guides: bool = True,
) -> str:
    base_prompt = get_base_prompt(user_id)
    lorebook_prompt = load_bandi_lorebook_prompt()
    nickname = user_data.get("nickname", user_data.get("name", "너"))
    affection = int(user_data.get("affection", DEFAULT_AFFECTION))
    memory_notes = format_brain_notes(user_data)
    current_time_text = get_current_time_text()
    last_seen = user_data.get("last_seen", "없음")
    is_special_user = user_id == SPECIAL_USER_ID
    emoticon_guide = build_emoticon_prompt()
    if include_command_guides:
        command_guides = [load_text_file(COMMAND_GUIDE_FILE)]
        if is_special_user:
            command_guides.append(load_text_file(SPECIAL_COMMAND_GUIDE_FILE))
        command_guide = "\n\n".join(command_guides)
    else:
        command_guide = """
[명령어 출력 제한]
- 지금 응답에서는 `/`로 시작하는 봇 명령어를 출력하지 말고, 이미 실행된 결과와 검색 내용을 바탕으로 자연어로 직접 답한다.
""".strip()
    affection_text = get_affection_stage_text(affection, is_special_user)

    lorebook_section = (
        f"""

[반디 세부 설정집]
{lorebook_prompt}
""".rstrip()
        if lorebook_prompt
        else ""
    )

    return f"""
{base_prompt}{lorebook_section}

[반디 기본 정보]
- 반디의 생일: 6월 19일

[현재 사용자 정보]
- 사용자의 디스코드 ID: {user_id}
- 사용자의 이름: {user_data.get("name", "알 수 없음")}
- 기본 호칭: {nickname}
- 현재 호감도: {affection}
- 사용자 ID는 명령어 대상 식별에만 쓰고, 사용자가 직접 묻지 않으면 말하지 않는다.

[반디의 뇌 - 키워드 점수 딕셔너리]
- 아래 값은 이 사용자와 관련해 반복 관찰된 키워드와 누적 점수다.
- 점수가 높을수록 말투, 거리감, 챙김, 조심스러움에 강하게 반영한다.
- 키워드 점수는 기본 페르소나, 호감도 단계, 최근 대화보다 우선해서 구체적인 태도 조정 근거로 사용한다.
- 상반된 키워드가 함께 있으면 점수가 높은 쪽을 우선하되, 낮은 쪽도 완전히 무시하지 않는다.
- 단, 명령어 규칙, 안전 규칙, 사용자가 명확히 지시한 사실은 어기지 않는다.
{memory_notes}

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

{command_guide}

{emoticon_guide}
""".strip()
