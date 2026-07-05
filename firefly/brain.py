import re
from dataclasses import dataclass

from .text_utils import clamp_text, get_current_time_text

BRAIN_NOTES_KEY = "brain_notes"
BRAIN_KEYWORDS_KEY = "brain_keywords"
SHORT_TERM_MEMORY_KEY = "short_term_memory"
LONG_TERM_MEMORY_KEY = "long_term_memory"
MEMORY_STATS_KEY = "memory_stats"

MEMORY_SCHEMA_VERSION = 2
KEYWORD_SCORE_DISCOUNT_RATE = 0.9
MAX_BRAIN_KEYWORDS = 50
MAX_KEYWORD_CHARS = 40
MIN_KEYWORD_SCORE = 0.1
MAX_KEYWORD_TOTAL_SCORE = 100.0
MIN_KEYWORD_UPDATE_SCORE = 1.0
MAX_KEYWORD_UPDATE_SCORE = 5.0

KEYWORD_ALIAS_GROUPS = {
    "애정표현": ("애정", "사랑", "좋아해", "호감", "보고싶", "보고 싶"),
    "감사": ("감사", "고마", "고맙"),
    "기쁨": ("기쁨", "즐거", "행복", "좋음", "웃음", "신남"),
    "서운함": ("서운", "속상", "상처", "섭섭"),
    "불편함": ("불편", "압박", "무례", "공격", "경계", "불신"),
    "신뢰": ("신뢰", "믿음", "믿어", "의지", "안심"),
    "사과": ("사과", "미안"),
    "짧은답변선호": ("짧은답", "짧게", "간단히", "요약", "결론먼저"),
    "확인질문싫음": ("확인질문", "되묻", "물어보지"),
    "작업방식": ("작업방식", "일하는방식", "진행방식", "코드", "구현", "테스트"),
    "프로젝트관심": ("프로젝트", "문서", "기능", "버그"),
}

KEYWORD_DERIVATION_RULES = (
    ("애정표현", ("사랑", "좋아해", "호감", "애정", "보고 싶"), 3.0),
    ("감사", ("고마", "감사"), 2.0),
    ("기쁨", ("기쁘", "즐거", "행복", "신나"), 2.0),
    ("서운함", ("서운", "속상", "상처", "섭섭"), 3.0),
    ("불편함", ("불편", "무례", "공격", "압박", "경계", "불신"), 3.0),
    ("신뢰", ("신뢰", "믿어", "의지", "안심"), 3.0),
    ("사과", ("미안", "사과"), 2.0),
    ("짧은답변선호", ("짧게", "짧고", "짧은", "짧은 답", "확실한 답", "요약", "결론 먼저"), 3.0),
    ("확인질문싫음", ("확인 질문", "되묻", "물어보지 마"), 3.0),
    ("작업방식", ("테스트", "구현", "코드", "작업 방식", "진행 방식"), 2.0),
    ("프로젝트관심", ("프로젝트", "문서화", "기능", "버그"), 2.0),
)

META_ASSIGNMENT_PATTERN = re.compile(
    r"\b(?:중요도|importance|범주|category|감정|affect|거리감|distance)\s*[:=]\s*\S+",
    re.IGNORECASE,
)
KEYWORD_SCORE_PAIR_PATTERN = re.compile(
    r"(?P<keyword>[^:=：|,\n]+?)\s*[:=：]\s*(?P<score>[+-]?\d+(?:\.\d+)?)"
)
KEYWORD_SCORE_TRAILING_PATTERN = re.compile(r"(?P<keyword>.+?)\s+(?P<score>[+-]?\d+(?:\.\d+)?)$")


@dataclass
class MemoryActionResult:
    status: str
    index: int
    entry: dict
    promoted_entry: dict | None = None
    reason: str | None = None


@dataclass(frozen=True)
class BrainMemoryDeleteTarget:
    memory_type: str | None
    index: int | None
    keyword: str | None = None


@dataclass(frozen=True)
class BrainMemoryDeleteResult:
    memory_type: str
    index: int | None
    contents: list[str]


def _now_text() -> str:
    return get_current_time_text()


def _format_score(score: object) -> str:
    try:
        value = float(score)
    except (TypeError, ValueError):
        value = 0.0
    if abs(value - round(value)) < 0.001:
        return str(int(round(value)))
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _compact_text(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "").casefold())


def _normalize_keyword_name(keyword: object) -> str:
    text = str(keyword or "").strip()
    text = META_ASSIGNMENT_PATTERN.sub("", text).strip()
    text = re.sub(r"^[\-*#\d\.\)\s]+", "", text)
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" \t\r\n:：=,|;\"'`[](){}")
    compact = _compact_text(text)

    for canonical, aliases in KEYWORD_ALIAS_GROUPS.items():
        canonical_compact = _compact_text(canonical)
        if compact == canonical_compact:
            return canonical
        if any(alias_compact and alias_compact in compact for alias_compact in map(_compact_text, aliases)):
            return canonical

    return clamp_text(text, MAX_KEYWORD_CHARS)


def _clamp_score(
    score: object,
    *,
    min_score: float = MIN_KEYWORD_UPDATE_SCORE,
    max_score: float = MAX_KEYWORD_UPDATE_SCORE,
) -> float:
    try:
        value = float(score)
    except (TypeError, ValueError):
        value = min_score
    return max(min_score, min(max_score, value))


def _normalize_keyword_scores(raw_scores: object) -> dict[str, float]:
    if isinstance(raw_scores, list):
        raw_scores = _scores_from_legacy_notes(raw_scores)
    if not isinstance(raw_scores, dict):
        return {}

    normalized: dict[str, float] = {}
    for raw_keyword, raw_score in raw_scores.items():
        keyword = _normalize_keyword_name(raw_keyword)
        if not keyword:
            continue
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            continue
        if score < MIN_KEYWORD_SCORE:
            continue
        normalized[keyword] = min(MAX_KEYWORD_TOTAL_SCORE, normalized.get(keyword, 0.0) + score)
    return _prune_keyword_scores(normalized)


def _derive_keywords_from_text(text: str) -> dict[str, float]:
    compact = _compact_text(text)
    updates: dict[str, float] = {}
    for keyword, signals, score in KEYWORD_DERIVATION_RULES:
        if any(_compact_text(signal) in compact for signal in signals):
            updates[keyword] = max(updates.get(keyword, 0.0), score)
    return updates


def _keyword_from_legacy_text(text: object) -> str:
    cleaned = META_ASSIGNMENT_PATTERN.sub("", str(text or "")).strip()
    cleaned = re.sub(r"^사용자는\s*", "", cleaned)
    cleaned = cleaned.rstrip(".。")
    keyword = _normalize_keyword_name(cleaned)
    return keyword or "일반관찰"


def _scores_from_legacy_notes(raw_notes: object) -> dict[str, float]:
    if isinstance(raw_notes, str):
        raw_notes = [raw_notes] if raw_notes.strip() else []
    if not isinstance(raw_notes, list):
        return {}

    scores: dict[str, float] = {}
    for raw_note in raw_notes:
        content = str(raw_note or "").strip()
        if not content:
            continue
        derived = _derive_keywords_from_text(content)
        if not derived:
            derived = {_keyword_from_legacy_text(content): 3.0}
        for keyword, score in derived.items():
            scores[keyword] = min(MAX_KEYWORD_TOTAL_SCORE, scores.get(keyword, 0.0) + score)
    return scores


def _scores_from_legacy_memory_entries(raw_entries: object) -> dict[str, float]:
    if not isinstance(raw_entries, list):
        return {}

    scores: dict[str, float] = {}
    for raw_entry in raw_entries:
        if isinstance(raw_entry, dict):
            content = str(raw_entry.get("content") or "").strip()
            frequency = raw_entry.get("frequency_score", 1)
            importance = raw_entry.get("importance_score", 0.6)
            try:
                score = max(float(frequency), float(importance) * MAX_KEYWORD_UPDATE_SCORE)
            except (TypeError, ValueError):
                score = 3.0
        else:
            content = str(raw_entry or "").strip()
            score = 3.0
        if not content:
            continue

        derived = _derive_keywords_from_text(content)
        if not derived:
            derived = {_keyword_from_legacy_text(content): _clamp_score(score)}
        for keyword, derived_score in derived.items():
            scores[keyword] = min(
                MAX_KEYWORD_TOTAL_SCORE,
                scores.get(keyword, 0.0) + _clamp_score(max(score, derived_score)),
            )
    return scores


def _merge_scores(base: dict[str, float], updates: dict[str, float]) -> dict[str, float]:
    merged = dict(base)
    for keyword, score in updates.items():
        normalized_keyword = _normalize_keyword_name(keyword)
        if not normalized_keyword:
            continue
        merged[normalized_keyword] = min(
            MAX_KEYWORD_TOTAL_SCORE,
            merged.get(normalized_keyword, 0.0) + float(score),
        )
    return _prune_keyword_scores(merged)


def _prune_keyword_scores(scores: dict[str, float]) -> dict[str, float]:
    kept = {
        keyword: round(float(score), 3)
        for keyword, score in scores.items()
        if keyword and float(score) >= MIN_KEYWORD_SCORE
    }
    return dict(
        sorted(
            kept.items(),
            key=lambda item: (-item[1], item[0]),
        )[:MAX_BRAIN_KEYWORDS]
    )


def _discount_keyword_scores(scores: dict[str, float]) -> dict[str, float]:
    return _prune_keyword_scores(
        {
            keyword: float(score) * KEYWORD_SCORE_DISCOUNT_RATE
            for keyword, score in scores.items()
        }
    )


def _sync_brain_notes(user_data: dict) -> None:
    scores = _normalize_keyword_scores(user_data.get(BRAIN_KEYWORDS_KEY))
    user_data[BRAIN_NOTES_KEY] = [
        f"{keyword}: {_format_score(score)}"
        for keyword, score in scores.items()
    ]


def _parse_keyword_updates(
    raw_text: str,
    *,
    max_score: float = MAX_KEYWORD_UPDATE_SCORE,
    allow_derived: bool = True,
) -> dict[str, float]:
    cleaned = str(raw_text or "").strip()
    updates: dict[str, float] = {}

    for match in KEYWORD_SCORE_PAIR_PATTERN.finditer(cleaned):
        keyword = _normalize_keyword_name(match.group("keyword"))
        if not keyword:
            continue
        updates[keyword] = updates.get(keyword, 0.0) + _clamp_score(
            match.group("score"),
            max_score=max_score,
        )

    if not updates:
        for chunk in re.split(r"[|,\n]+", cleaned):
            match = KEYWORD_SCORE_TRAILING_PATTERN.fullmatch(chunk.strip())
            if not match:
                continue
            keyword = _normalize_keyword_name(match.group("keyword"))
            if not keyword:
                continue
            updates[keyword] = updates.get(keyword, 0.0) + _clamp_score(
                match.group("score"),
                max_score=max_score,
            )

    if not updates and allow_derived:
        updates = _derive_keywords_from_text(cleaned)

    return _prune_keyword_scores(updates)


def _keyword_items(user_data: dict) -> list[tuple[str, float]]:
    normalize_user_memory(user_data)
    return list(user_data[BRAIN_KEYWORDS_KEY].items())


def _keyword_index(user_data: dict, keyword: str) -> int:
    for index, (existing_keyword, _) in enumerate(_keyword_items(user_data), start=1):
        if existing_keyword == keyword:
            return index
    return 0


def normalize_user_memory(user_data: dict) -> dict:
    stats = user_data.get(MEMORY_STATS_KEY)
    if not isinstance(stats, dict):
        stats = {}

    try:
        schema_version = int(stats.get("schema_version", 0))
    except (TypeError, ValueError):
        schema_version = 0

    scores = _normalize_keyword_scores(user_data.get(BRAIN_KEYWORDS_KEY))
    if schema_version < MEMORY_SCHEMA_VERSION:
        scores = _merge_scores(scores, _scores_from_legacy_notes(user_data.get(BRAIN_NOTES_KEY)))
        scores = _merge_scores(scores, _scores_from_legacy_memory_entries(user_data.get(LONG_TERM_MEMORY_KEY)))
        scores = _merge_scores(scores, _scores_from_legacy_memory_entries(user_data.get(SHORT_TERM_MEMORY_KEY)))

    user_data[BRAIN_KEYWORDS_KEY] = _prune_keyword_scores(scores)
    user_data[SHORT_TERM_MEMORY_KEY] = []
    user_data[LONG_TERM_MEMORY_KEY] = []

    stats["schema_version"] = MEMORY_SCHEMA_VERSION
    stats.setdefault("keyword_discount_rate", KEYWORD_SCORE_DISCOUNT_RATE)
    stats.setdefault("keyword_total_updates", 0)
    stats.setdefault("last_keyword_update_at", None)
    user_data[MEMORY_STATS_KEY] = stats

    _sync_brain_notes(user_data)
    return user_data


def normalize_brain_notes(user_data: dict) -> list[str]:
    normalize_user_memory(user_data)
    return user_data[BRAIN_NOTES_KEY]


def add_brain_note(user_data: dict, note: str) -> MemoryActionResult:
    updates = _parse_keyword_updates(note)
    if not updates:
        raise ValueError("키워드와 1~5점 점수를 같이 적어줘. 예: `애정표현: 3 | 기쁨: 2`")

    normalize_user_memory(user_data)
    discounted_scores = _discount_keyword_scores(user_data[BRAIN_KEYWORDS_KEY])
    new_scores = _merge_scores(discounted_scores, updates)
    user_data[BRAIN_KEYWORDS_KEY] = new_scores

    stats = user_data[MEMORY_STATS_KEY]
    stats["keyword_total_updates"] = int(stats.get("keyword_total_updates", 0)) + len(updates)
    stats["last_keyword_update_at"] = _now_text()
    stats["keyword_discount_rate"] = KEYWORD_SCORE_DISCOUNT_RATE
    _sync_brain_notes(user_data)

    first_keyword = next(iter(updates))
    updated_scores = {
        keyword: new_scores[keyword]
        for keyword in updates
        if keyword in new_scores
    }
    return MemoryActionResult(
        status="updated",
        index=_keyword_index(user_data, first_keyword),
        entry={
            "updates": updates,
            "updated_scores": updated_scores,
            BRAIN_KEYWORDS_KEY: dict(new_scores),
        },
        reason=f"기존 키워드에 할인률 {KEYWORD_SCORE_DISCOUNT_RATE:.2f} 적용 후 누적",
    )


def update_brain_note(user_data: dict, index: int, note: str) -> bool:
    items = _keyword_items(user_data)
    if index < 1 or index > len(items):
        return False

    old_keyword, old_score = items[index - 1]
    updates = _parse_keyword_updates(
        note,
        max_score=MAX_KEYWORD_TOTAL_SCORE,
        allow_derived=False,
    )
    scores = dict(user_data[BRAIN_KEYWORDS_KEY])
    scores.pop(old_keyword, None)

    if updates:
        keyword, score = next(iter(updates.items()))
        scores[keyword] = min(MAX_KEYWORD_TOTAL_SCORE, score)
    else:
        keyword = _normalize_keyword_name(note)
        if not keyword:
            return False
        scores[keyword] = old_score

    user_data[BRAIN_KEYWORDS_KEY] = _prune_keyword_scores(scores)
    user_data[MEMORY_STATS_KEY]["last_keyword_update_at"] = _now_text()
    _sync_brain_notes(user_data)
    return True


def delete_brain_note(user_data: dict, index: int) -> str | None:
    result = delete_brain_memory(user_data, BrainMemoryDeleteTarget(memory_type=BRAIN_KEYWORDS_KEY, index=index))
    if result is None:
        return None
    return result.contents[0]


def delete_brain_memory(user_data: dict, target: BrainMemoryDeleteTarget) -> BrainMemoryDeleteResult | None:
    items = _keyword_items(user_data)
    scores = dict(user_data[BRAIN_KEYWORDS_KEY])

    keyword: str | None = None
    index = target.index
    if index is not None:
        if index < 1 or index > len(items):
            return None
        keyword = items[index - 1][0]
    elif target.keyword:
        normalized = _normalize_keyword_name(target.keyword)
        keyword = normalized if normalized in scores else None
        if keyword is None:
            return None
        index = _keyword_index(user_data, keyword)
    else:
        return None

    removed_score = scores.pop(keyword, None)
    if removed_score is None:
        return None

    user_data[BRAIN_KEYWORDS_KEY] = _prune_keyword_scores(scores)
    user_data[MEMORY_STATS_KEY]["last_keyword_update_at"] = _now_text()
    _sync_brain_notes(user_data)
    return BrainMemoryDeleteResult(
        memory_type=BRAIN_KEYWORDS_KEY,
        index=index,
        contents=[f"{keyword}: {_format_score(removed_score)}"],
    )


def format_brain_notes(user_data: dict) -> str:
    normalize_user_memory(user_data)
    scores = user_data[BRAIN_KEYWORDS_KEY]
    if not scores:
        return "아직 저장된 키워드 점수가 없음"

    inline = " | ".join(
        f"{keyword}: {_format_score(score)}"
        for keyword, score in scores.items()
    )
    return (
        "[키워드 점수 딕셔너리]\n"
        f"{inline}\n"
        f"(업데이트 시 기존 점수에는 할인률 {KEYWORD_SCORE_DISCOUNT_RATE:.2f}이 먼저 적용됨)"
    )


def parse_brain_index_and_note(raw_text: str) -> tuple[int | None, str]:
    parts = raw_text.strip().split(maxsplit=1)
    if not parts or not parts[0].isdigit():
        return None, ""

    index = int(parts[0])
    note = parts[1].strip() if len(parts) > 1 else ""
    return index, note


def parse_brain_delete_target(raw_text: str) -> BrainMemoryDeleteTarget | None:
    text = raw_text.strip()
    if not text:
        return None

    token = text.split(maxsplit=1)[0]
    compact = re.sub(r"[\s#._-]+", "", token.casefold())
    number_match = re.fullmatch(r"(?:k|키워드)?(\d+)(?:번)?", compact)
    if number_match:
        return BrainMemoryDeleteTarget(
            memory_type=BRAIN_KEYWORDS_KEY,
            index=int(number_match.group(1)),
        )

    keyword = _normalize_keyword_name(text)
    if not keyword:
        return None
    return BrainMemoryDeleteTarget(memory_type=BRAIN_KEYWORDS_KEY, index=None, keyword=keyword)
