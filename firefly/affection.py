from .config import DEFAULT_AFFECTION, SPECIAL_USER_ID
from .content import NEGATIVE_KEYWORDS, POSITIVE_KEYWORDS
from .storage import load_memory, save_memory
from .text_utils import normalize_text


def _ensure_user_entry(all_data: dict, target_user_id: int) -> dict:
    key = str(target_user_id)
    if key not in all_data:
        all_data[key] = {
            "name": "알 수 없음",
            "nickname": "개척자",
            "affection": DEFAULT_AFFECTION,
            "last_seen": None,
            "history": [],
        }
    return all_data[key]


def set_user_affection(target_user_id: int, value: int) -> int:
    all_data = load_memory()
    user_data = _ensure_user_entry(all_data, target_user_id)

    if target_user_id == SPECIAL_USER_ID:
        user_data["affection"] = 1004
    else:
        user_data["affection"] = max(1, min(100, value))

    save_memory(all_data)
    return user_data["affection"]


def change_user_affection(target_user_id: int, delta: int) -> int:
    all_data = load_memory()
    user_data = _ensure_user_entry(all_data, target_user_id)
    current = user_data.get("affection", DEFAULT_AFFECTION)

    if target_user_id == SPECIAL_USER_ID:
        user_data["affection"] = 1004
    else:
        user_data["affection"] = max(1, min(100, current + delta))

    save_memory(all_data)
    return user_data["affection"]


def adjust_affection(user_id: int, user_data: dict, user_message: str) -> dict:
    if user_id == SPECIAL_USER_ID:
        user_data["affection"] = 1004
        return user_data

    affection = int(user_data.get("affection", DEFAULT_AFFECTION))
    text = normalize_text(user_message.strip())

    positive_hit = any(normalize_text(word) in text for word in POSITIVE_KEYWORDS)
    negative_hit = any(normalize_text(word) in text for word in NEGATIVE_KEYWORDS)

    if positive_hit:
        affection += 1

    if negative_hit:
        affection -= 3

    user_data["affection"] = max(1, min(100, affection))
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


def get_affection_stage_label(affection: int) -> str:
    if 1 <= affection <= 20:
        return "쌀쌀맞은 상태"
    if 21 <= affection <= 40:
        return "조금 쌀쌀맞은 상태"
    if 41 <= affection <= 60:
        return "평범한 거리감"
    if 61 <= affection <= 80:
        return "조금 친한 상태"
    if 81 <= affection <= 100:
        return "친한 친구 수준"
    if affection == 1004:
        return "특별한 존재"
    return "알 수 없음"
