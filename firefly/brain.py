import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from .text_utils import clamp_text, get_current_time_text

BRAIN_NOTES_KEY = "brain_notes"
SHORT_TERM_MEMORY_KEY = "short_term_memory"
LONG_TERM_MEMORY_KEY = "long_term_memory"
MEMORY_STATS_KEY = "memory_stats"

MEMORY_SCHEMA_VERSION = 1
MAX_BRAIN_NOTES = 50
MAX_BRAIN_NOTE_CHARS = 400
MAX_SHORT_TERM_MEMORIES = 30
MAX_LONG_TERM_MEMORIES = 50
SHORT_TERM_MEMORY_TTL_DAYS = 14
PROMOTION_FREQUENCY_THRESHOLD = 3
PROMOTION_IMPORTANCE_THRESHOLD = 0.85
SPARSE_PROFILE_MEMORY_LIMIT = 2
DENSE_MEMORY_LIMIT = 8
ABRUPT_RELATIONSHIP_INTENSITY_THRESHOLD = 0.9
DEFAULT_IMPORTANCE_SCORE = 0.55

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

RELATIONSHIP_KEYWORDS = (
    "관계", "신뢰", "불신", "배려", "존중", "무례", "공격", "기만", "거짓", "거리",
    "가깝", "편안", "불편", "경계", "상처", "사과", "고마", "의지", "압박",
    "선 넘", "따뜻", "차갑", "조심", "안심", "서운", "친절", "날카롭",
    "호감", "애정",
)
POSITIVE_AFFECT_KEYWORDS = (
    "신뢰", "배려", "존중", "편안", "사과", "고마", "의지", "따뜻", "안심", "친절",
    "호감", "애정",
)
NEGATIVE_AFFECT_KEYWORDS = (
    "불신", "무례", "공격", "기만", "거짓", "불편", "경계", "상처", "압박",
    "선 넘", "차갑", "서운", "날카롭",
)
ABRUPT_CHANGE_KEYWORDS = (
    "갑자기", "급격", "처음으로", "이례적", "확실히", "크게", "심하게", "완전히",
)
PREFERENCE_KEYWORDS = ("선호", "좋아", "싫어", "답변", "설명", "요약", "말투", "방식")
PROJECT_KEYWORDS = ("프로젝트", "문서", "테스트", "코드", "작업", "기능", "버그", "구현")
ROUTINE_AFFECTION_KEYWORDS = (
    "좋아해", "사랑해", "애정", "호감", "보고 싶", "고마워", "고맙",
)
RELATIONSHIP_TARGET_KEYWORDS = ("반디", "나를", "나에게", "내게", "봇에게")


@dataclass
class MemoryActionResult:
    status: str
    index: int
    entry: dict
    promoted_entry: dict | None = None
    reason: str | None = None


def _now_text() -> str:
    return get_current_time_text()


def _normalize_content(content: object) -> str:
    return clamp_text(str(content or "").strip(), MAX_BRAIN_NOTE_CHARS)


def _content_key(content: object) -> str:
    return re.sub(r"\s+", " ", str(content or "").strip()).casefold()


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.strptime(value.strip(), TIMESTAMP_FORMAT)
    except ValueError:
        return None


def _to_score(value: object, default: float) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = default
    return max(0.0, min(1.0, score))


def _to_frequency(value: object) -> int:
    try:
        frequency = int(value)
    except (TypeError, ValueError):
        frequency = 1
    return max(1, frequency)


def _keyword_count(content: str, keywords: tuple[str, ...]) -> int:
    compact = content.casefold()
    return sum(1 for keyword in keywords if keyword.casefold() in compact)


def _has_targeted_affection(content: str) -> bool:
    compact = content.casefold()
    return (
        any(keyword.casefold() in compact for keyword in ROUTINE_AFFECTION_KEYWORDS)
        and any(keyword.casefold() in compact for keyword in RELATIONSHIP_TARGET_KEYWORDS)
    )


def _is_routine_affection(content: str, metadata: dict) -> bool:
    if metadata.get("memory_category") != "relationship":
        return False
    if _to_score(metadata.get("emotional_intensity_score"), 0.0) >= ABRUPT_RELATIONSHIP_INTENSITY_THRESHOLD:
        return False
    if _to_score(metadata.get("importance_score"), DEFAULT_IMPORTANCE_SCORE) >= PROMOTION_IMPORTANCE_THRESHOLD:
        return False
    return _has_targeted_affection(content)


def _score_from_affect_label(value: object) -> float | None:
    label = str(value or "").strip().casefold()
    if not label:
        return None
    score_map = {
        "긍정": 0.55,
        "좋음": 0.55,
        "신뢰": 0.7,
        "편안": 0.55,
        "negative": -0.55,
        "부정": -0.55,
        "나쁨": -0.55,
        "불편": -0.55,
        "경계": -0.9,
        "불신": -0.9,
        "positive": 0.55,
        "trust": 0.7,
        "guarded": -0.9,
    }
    if label in score_map:
        return score_map[label]
    try:
        return max(-1.0, min(1.0, float(label)))
    except ValueError:
        return None


def _distance_from_label(value: object) -> float | None:
    label = str(value or "").strip().casefold()
    if not label:
        return None
    score_map = {
        "가까움": 0.2,
        "가깝": 0.2,
        "편안": 0.25,
        "보통": 0.5,
        "중립": 0.5,
        "조심": 0.7,
        "경계": 0.85,
        "거리둠": 0.9,
        "멀게": 0.9,
        "close": 0.2,
        "neutral": 0.5,
        "careful": 0.7,
        "guarded": 0.85,
        "distant": 0.9,
    }
    if label in score_map:
        return score_map[label]
    try:
        return max(0.0, min(1.0, float(label)))
    except ValueError:
        return None


def _normalize_category(value: object) -> str | None:
    label = str(value or "").strip().casefold()
    if not label:
        return None
    if label in {"관계", "감정", "거리", "거리감", "신뢰", "relationship", "affect"}:
        return "relationship"
    if label in {"선호", "취향", "말투", "preference"}:
        return "preference"
    if label in {"프로젝트", "작업", "project", "work"}:
        return "project"
    return None


def _memory_id(memory_type: str, content: str, created_at: str) -> str:
    digest = hashlib.sha1(f"{memory_type}:{created_at}:{content}".encode("utf-8")).hexdigest()[:12]
    return f"{memory_type[:2]}_{digest}"


def _importance_label_to_score(raw_score: object) -> float:
    label = str(raw_score or "").strip().casefold()
    score_map = {
        "높음": 0.95,
        "high": 0.95,
        "중간": 0.65,
        "보통": 0.65,
        "medium": 0.65,
        "낮음": 0.35,
        "low": 0.35,
    }
    if label in score_map:
        return score_map[label]
    return _to_score(label, DEFAULT_IMPORTANCE_SCORE)


def _extract_candidate_metadata(content: str) -> tuple[str, dict]:
    metadata = {
        "importance_score": DEFAULT_IMPORTANCE_SCORE,
        "memory_category": None,
        "affective_score": None,
        "distance_score": None,
    }
    cleaned = content.strip()
    prefix_pattern = re.compile(
        r"^(중요도|importance|범주|category|감정|affect|거리감|distance)\s*[:=]\s*(\S+)\s+",
        re.IGNORECASE,
    )

    while True:
        match = prefix_pattern.match(cleaned)
        if not match:
            break
        key = match.group(1).casefold()
        value = match.group(2)
        cleaned = cleaned[match.end():].strip()

        if key in {"중요도", "importance"}:
            metadata["importance_score"] = _importance_label_to_score(value)
        elif key in {"범주", "category"}:
            metadata["memory_category"] = _normalize_category(value)
        elif key in {"감정", "affect"}:
            metadata["affective_score"] = _score_from_affect_label(value)
            metadata["memory_category"] = metadata["memory_category"] or "relationship"
        elif key in {"거리감", "distance"}:
            metadata["distance_score"] = _distance_from_label(value)
            metadata["memory_category"] = metadata["memory_category"] or "relationship"

    return cleaned, metadata


def _classify_memory_content(
    content: str,
    metadata: dict | None = None,
) -> dict:
    metadata = dict(metadata or {})
    positive_count = _keyword_count(content, POSITIVE_AFFECT_KEYWORDS)
    negative_count = _keyword_count(content, NEGATIVE_AFFECT_KEYWORDS)
    relationship_count = _keyword_count(content, RELATIONSHIP_KEYWORDS)
    targeted_affection = _has_targeted_affection(content)
    abrupt_count = _keyword_count(content, ABRUPT_CHANGE_KEYWORDS)

    category = metadata.get("memory_category")
    if category is None:
        if relationship_count or targeted_affection:
            category = "relationship"
        elif _keyword_count(content, PROJECT_KEYWORDS):
            category = "project"
        elif _keyword_count(content, PREFERENCE_KEYWORDS):
            category = "preference"
        else:
            category = "general"

    affective_score = metadata.get("affective_score")
    if affective_score is None:
        affective_score = max(-1.0, min(1.0, (positive_count - negative_count) * 0.25))

    distance_score = metadata.get("distance_score")
    if distance_score is None:
        if negative_count:
            distance_score = min(1.0, 0.55 + negative_count * 0.12)
        elif positive_count:
            distance_score = max(0.0, 0.45 - positive_count * 0.1)
        else:
            distance_score = 0.5

    importance_score = _to_score(metadata.get("importance_score"), DEFAULT_IMPORTANCE_SCORE)
    if category == "relationship":
        importance_score = max(importance_score, 0.65)

    emotional_intensity_score = max(
        abs(float(affective_score)),
        abs(0.5 - float(distance_score)) * 2,
        min(1.0, abrupt_count * 0.35 + (positive_count + negative_count) * 0.15),
    )

    return {
        "importance_score": importance_score,
        "memory_category": category,
        "affective_score": max(-1.0, min(1.0, float(affective_score))),
        "distance_score": max(0.0, min(1.0, float(distance_score))),
        "emotional_intensity_score": max(0.0, min(1.0, emotional_intensity_score)),
    }


def _new_memory_entry(
    *,
    memory_type: str,
    content: str,
    importance_score: float = DEFAULT_IMPORTANCE_SCORE,
    frequency_score: int = 1,
    now: str | None = None,
    promotion_reason: str | None = None,
    metadata: dict | None = None,
) -> dict:
    timestamp = now or _now_text()
    classified = _classify_memory_content(
        content,
        {"importance_score": importance_score, **(metadata or {})},
    )
    entry = {
        "memory_id": _memory_id(memory_type, content, timestamp),
        "memory_type": memory_type,
        "content": content,
        "importance_score": classified["importance_score"],
        "frequency_score": _to_frequency(frequency_score),
        "memory_category": classified["memory_category"],
        "affective_score": classified["affective_score"],
        "distance_score": classified["distance_score"],
        "emotional_intensity_score": classified["emotional_intensity_score"],
        "created_at": timestamp,
        "updated_at": timestamp,
        "last_used_at": timestamp,
    }
    if promotion_reason:
        entry["promotion_reason"] = promotion_reason
        entry["promoted_at"] = timestamp
    return entry


def _normalize_memory_entry(raw_entry: object, memory_type: str) -> dict | None:
    if isinstance(raw_entry, str):
        content = _normalize_content(raw_entry)
        if not content:
            return None
        return _new_memory_entry(
            memory_type=memory_type,
            content=content,
            importance_score=(
                PROMOTION_IMPORTANCE_THRESHOLD
                if memory_type == "long_term"
                else DEFAULT_IMPORTANCE_SCORE
            ),
            promotion_reason="legacy string migration" if memory_type == "long_term" else None,
        )

    if not isinstance(raw_entry, dict):
        return None

    content = _normalize_content(raw_entry.get("content"))
    if not content:
        return None

    now = _now_text()
    created_at = str(raw_entry.get("created_at") or now)
    updated_at = str(raw_entry.get("updated_at") or created_at)
    last_used_at = str(raw_entry.get("last_used_at") or updated_at)
    entry = {
        "memory_id": str(raw_entry.get("memory_id") or _memory_id(memory_type, content, created_at)),
        "memory_type": memory_type,
        "content": content,
        "importance_score": _to_score(raw_entry.get("importance_score"), DEFAULT_IMPORTANCE_SCORE),
        "frequency_score": _to_frequency(raw_entry.get("frequency_score")),
        "memory_category": _normalize_category(raw_entry.get("memory_category")),
        "affective_score": _score_from_affect_label(raw_entry.get("affective_score")),
        "distance_score": _distance_from_label(raw_entry.get("distance_score")),
        "created_at": created_at,
        "updated_at": updated_at,
        "last_used_at": last_used_at,
    }
    classified = _classify_memory_content(content, entry)
    entry.update(classified)
    if memory_type == "long_term":
        entry["promotion_reason"] = str(raw_entry.get("promotion_reason") or "normalized long-term memory")
        entry["promoted_at"] = str(raw_entry.get("promoted_at") or created_at)
    return entry


def _dedupe_memories(entries: list[dict]) -> list[dict]:
    deduped = {}
    order = []
    for entry in entries:
        key = _content_key(entry.get("content"))
        if not key:
            continue
        if key not in deduped:
            deduped[key] = entry
            order.append(key)
            continue
        existing = deduped[key]
        existing["frequency_score"] = max(
            _to_frequency(existing.get("frequency_score")),
            _to_frequency(entry.get("frequency_score")),
        )
        existing["importance_score"] = max(
            _to_score(existing.get("importance_score"), DEFAULT_IMPORTANCE_SCORE),
            _to_score(entry.get("importance_score"), DEFAULT_IMPORTANCE_SCORE),
        )
        existing["updated_at"] = max(str(existing.get("updated_at", "")), str(entry.get("updated_at", "")))
        existing["last_used_at"] = max(str(existing.get("last_used_at", "")), str(entry.get("last_used_at", "")))
    return [deduped[key] for key in order]


def _merge_memory_metadata(entry: dict, metadata: dict) -> None:
    content = str(entry.get("content", ""))
    classified = _classify_memory_content(content, metadata)
    entry["importance_score"] = max(
        _to_score(entry.get("importance_score"), DEFAULT_IMPORTANCE_SCORE),
        classified["importance_score"],
    )
    entry["emotional_intensity_score"] = max(
        _to_score(entry.get("emotional_intensity_score"), 0.0),
        classified["emotional_intensity_score"],
    )
    if classified["memory_category"] == "relationship" or not entry.get("memory_category"):
        entry["memory_category"] = classified["memory_category"]
    entry["affective_score"] = classified["affective_score"]
    entry["distance_score"] = classified["distance_score"]


def _memory_count(user_data: dict) -> int:
    return len(user_data.get(SHORT_TERM_MEMORY_KEY, [])) + len(user_data.get(LONG_TERM_MEMORY_KEY, []))


def _relationship_memory_count(user_data: dict) -> int:
    return sum(
        1
        for entry in user_data.get(SHORT_TERM_MEMORY_KEY, []) + user_data.get(LONG_TERM_MEMORY_KEY, [])
        if entry.get("memory_category") == "relationship"
    )


def _is_established_profile(user_data: dict) -> bool:
    return _memory_count(user_data) >= DENSE_MEMORY_LIMIT or _relationship_memory_count(user_data) >= 3


def _should_store_candidate(user_data: dict, content: str, metadata: dict) -> bool:
    if not _is_routine_affection(content, metadata):
        return True
    if _memory_count(user_data) <= SPARSE_PROFILE_MEMORY_LIMIT:
        return True
    return not _is_established_profile(user_data)


class MemoryStorage:
    @staticmethod
    def normalize_user_data(user_data: dict) -> dict:
        if not isinstance(user_data.get(SHORT_TERM_MEMORY_KEY), list):
            user_data[SHORT_TERM_MEMORY_KEY] = []
        if not isinstance(user_data.get(LONG_TERM_MEMORY_KEY), list):
            user_data[LONG_TERM_MEMORY_KEY] = []

        short_term = [
            entry
            for entry in (
                _normalize_memory_entry(raw_entry, "short_term")
                for raw_entry in user_data.get(SHORT_TERM_MEMORY_KEY, [])
            )
            if entry is not None
        ]
        long_term = [
            entry
            for entry in (
                _normalize_memory_entry(raw_entry, "long_term")
                for raw_entry in user_data.get(LONG_TERM_MEMORY_KEY, [])
            )
            if entry is not None
        ]

        legacy_notes = _normalize_legacy_brain_notes(user_data.get(BRAIN_NOTES_KEY, []))
        existing_long_term_keys = {_content_key(entry["content"]) for entry in long_term}
        for note in legacy_notes:
            if _content_key(note) in existing_long_term_keys:
                continue
            long_term.append(
                _new_memory_entry(
                    memory_type="long_term",
                    content=note,
                    importance_score=PROMOTION_IMPORTANCE_THRESHOLD,
                    promotion_reason="legacy brain_notes migration",
                )
            )
            existing_long_term_keys.add(_content_key(note))

        user_data[SHORT_TERM_MEMORY_KEY] = ShortTermMemoryManager.prune(_dedupe_memories(short_term))
        user_data[LONG_TERM_MEMORY_KEY] = _dedupe_memories(long_term)[-MAX_LONG_TERM_MEMORIES:]

        stats = user_data.get(MEMORY_STATS_KEY)
        if not isinstance(stats, dict):
            stats = {}
        stats.setdefault("schema_version", MEMORY_SCHEMA_VERSION)
        stats.setdefault("short_term_total_created", len(user_data[SHORT_TERM_MEMORY_KEY]))
        stats.setdefault("long_term_total_promoted", len(user_data[LONG_TERM_MEMORY_KEY]))
        stats.setdefault("last_promoted_at", None)
        user_data[MEMORY_STATS_KEY] = stats

        _sync_brain_notes(user_data)
        return user_data


class ShortTermMemoryManager:
    @staticmethod
    def prune(entries: list[dict]) -> list[dict]:
        cutoff = datetime.now() - timedelta(days=SHORT_TERM_MEMORY_TTL_DAYS)
        kept = []
        for entry in entries:
            created_at = _parse_timestamp(entry.get("created_at"))
            if created_at is not None and created_at < cutoff:
                continue
            kept.append(entry)
        return kept[-MAX_SHORT_TERM_MEMORIES:]

    @staticmethod
    def add_candidate(user_data: dict, content: str, metadata: dict) -> MemoryActionResult:
        normalize_user_memory(user_data)
        now = _now_text()
        if not _should_store_candidate(user_data, content, metadata):
            return MemoryActionResult(status="ignored", index=0, entry={})

        content_key = _content_key(content)
        importance_score = _to_score(metadata.get("importance_score"), DEFAULT_IMPORTANCE_SCORE)

        existing_long_term = _find_memory_by_content(user_data[LONG_TERM_MEMORY_KEY], content_key)
        if existing_long_term is not None:
            existing_long_term["frequency_score"] = _to_frequency(existing_long_term.get("frequency_score")) + 1
            _merge_memory_metadata(existing_long_term, metadata)
            existing_long_term["updated_at"] = now
            existing_long_term["last_used_at"] = now
            _sync_brain_notes(user_data)
            return MemoryActionResult(
                status="merged_long_term",
                index=user_data[LONG_TERM_MEMORY_KEY].index(existing_long_term) + 1,
                entry=existing_long_term,
            )

        existing_short_term = _find_memory_by_content(user_data[SHORT_TERM_MEMORY_KEY], content_key)
        if existing_short_term is not None:
            existing_short_term["frequency_score"] = _to_frequency(existing_short_term.get("frequency_score")) + 1
            _merge_memory_metadata(existing_short_term, metadata)
            existing_short_term["updated_at"] = now
            existing_short_term["last_used_at"] = now
            return MemoryManager.evaluate_candidate(user_data, existing_short_term)

        entry = _new_memory_entry(
            memory_type="short_term",
            content=content,
            importance_score=importance_score,
            now=now,
            metadata=metadata,
        )
        user_data[SHORT_TERM_MEMORY_KEY].append(entry)
        user_data[SHORT_TERM_MEMORY_KEY] = ShortTermMemoryManager.prune(user_data[SHORT_TERM_MEMORY_KEY])
        stats = user_data[MEMORY_STATS_KEY]
        stats["short_term_total_created"] = int(stats.get("short_term_total_created", 0)) + 1
        return MemoryManager.evaluate_candidate(user_data, entry)


class LongTermMemoryManager:
    @staticmethod
    def promote(user_data: dict, entry: dict, reason: str) -> MemoryActionResult:
        now = _now_text()
        content = _normalize_content(entry.get("content"))
        promoted_entry = dict(entry)
        promoted_entry["memory_type"] = "long_term"
        promoted_entry["memory_id"] = _memory_id("long_term", content, str(entry.get("created_at") or now))
        promoted_entry["content"] = content
        promoted_entry["updated_at"] = now
        promoted_entry["last_used_at"] = now
        promoted_entry["promotion_reason"] = reason
        promoted_entry["promoted_at"] = now

        user_data[SHORT_TERM_MEMORY_KEY] = [
            item
            for item in user_data[SHORT_TERM_MEMORY_KEY]
            if item.get("memory_id") != entry.get("memory_id")
        ]
        user_data[LONG_TERM_MEMORY_KEY].append(promoted_entry)
        user_data[LONG_TERM_MEMORY_KEY] = _dedupe_memories(user_data[LONG_TERM_MEMORY_KEY])[-MAX_LONG_TERM_MEMORIES:]
        stats = user_data[MEMORY_STATS_KEY]
        stats["long_term_total_promoted"] = int(stats.get("long_term_total_promoted", 0)) + 1
        stats["last_promoted_at"] = now
        _sync_brain_notes(user_data)
        return MemoryActionResult(
            status="promoted",
            index=user_data[LONG_TERM_MEMORY_KEY].index(promoted_entry) + 1,
            entry=entry,
            promoted_entry=promoted_entry,
            reason=reason,
        )

    @staticmethod
    def update(user_data: dict, index: int, content: str) -> bool:
        normalize_user_memory(user_data)
        normalized_content = _normalize_content(content)
        if not normalized_content or index < 1 or index > len(user_data[LONG_TERM_MEMORY_KEY]):
            return False
        entry = user_data[LONG_TERM_MEMORY_KEY][index - 1]
        entry["content"] = normalized_content
        entry["updated_at"] = _now_text()
        entry["last_used_at"] = entry["updated_at"]
        _sync_brain_notes(user_data)
        return True

    @staticmethod
    def delete(user_data: dict, index: int) -> str | None:
        normalize_user_memory(user_data)
        if index < 1 or index > len(user_data[LONG_TERM_MEMORY_KEY]):
            return None
        deleted = user_data[LONG_TERM_MEMORY_KEY].pop(index - 1)
        _sync_brain_notes(user_data)
        return str(deleted.get("content", ""))


class MemoryManager:
    @staticmethod
    def add_candidate(user_data: dict, raw_content: str) -> MemoryActionResult:
        content, metadata = _extract_candidate_metadata(_normalize_content(raw_content))
        if not content:
            raise ValueError("저장할 평가 내용이 비어 있어.")
        classified_metadata = _classify_memory_content(content, metadata)
        return ShortTermMemoryManager.add_candidate(user_data, content, classified_metadata)

    @staticmethod
    def evaluate_candidate(user_data: dict, entry: dict) -> MemoryActionResult:
        reason = promotion_reason(entry, user_data)
        if reason:
            return LongTermMemoryManager.promote(user_data, entry, reason)
        index = user_data[SHORT_TERM_MEMORY_KEY].index(entry) + 1
        return MemoryActionResult(status="short_term", index=index, entry=entry)


def _find_memory_by_content(entries: list[dict], content_key: str) -> dict | None:
    for entry in entries:
        if _content_key(entry.get("content")) == content_key:
            return entry
    return None


def _normalize_legacy_brain_notes(raw_notes: object) -> list[str]:
    if isinstance(raw_notes, str):
        raw_notes = [raw_notes] if raw_notes.strip() else []
    elif not isinstance(raw_notes, list):
        raw_notes = []
    notes = []
    for raw_note in raw_notes:
        note = _normalize_content(raw_note)
        if note:
            notes.append(note)
    return notes[-MAX_BRAIN_NOTES:]


def _sync_brain_notes(user_data: dict) -> None:
    user_data[BRAIN_NOTES_KEY] = [
        entry["content"]
        for entry in user_data.get(LONG_TERM_MEMORY_KEY, [])[-MAX_BRAIN_NOTES:]
        if _normalize_content(entry.get("content"))
    ]


def promotion_reason(entry: dict, user_data: dict | None = None) -> str | None:
    importance_score = _to_score(entry.get("importance_score"), DEFAULT_IMPORTANCE_SCORE)
    frequency_score = _to_frequency(entry.get("frequency_score"))
    emotional_intensity_score = _to_score(entry.get("emotional_intensity_score"), 0.0)
    is_relationship = entry.get("memory_category") == "relationship"

    if is_relationship and emotional_intensity_score >= ABRUPT_RELATIONSHIP_INTENSITY_THRESHOLD:
        return f"급격한 관계 변화 강도 {emotional_intensity_score:.2f}가 장기 기억 기준을 넘음"
    if importance_score >= PROMOTION_IMPORTANCE_THRESHOLD:
        return f"중요도 {importance_score:.2f}가 장기 기억 기준 {PROMOTION_IMPORTANCE_THRESHOLD:.2f}를 넘음"
    if frequency_score >= PROMOTION_FREQUENCY_THRESHOLD:
        return f"반복 등장 {frequency_score}회가 장기 기억 기준 {PROMOTION_FREQUENCY_THRESHOLD}회를 넘음"
    return None


def normalize_user_memory(user_data: dict) -> dict:
    return MemoryStorage.normalize_user_data(user_data)


def normalize_brain_notes(user_data: dict) -> list[str]:
    normalize_user_memory(user_data)
    return user_data[BRAIN_NOTES_KEY]


def add_brain_note(user_data: dict, note: str) -> MemoryActionResult:
    return MemoryManager.add_candidate(user_data, note)


def update_brain_note(user_data: dict, index: int, note: str) -> bool:
    return LongTermMemoryManager.update(user_data, index, note)


def delete_brain_note(user_data: dict, index: int) -> str | None:
    return LongTermMemoryManager.delete(user_data, index)


def _format_memory_metadata(entry: dict) -> str:
    return (
        f"범주={entry.get('memory_category', 'general')}, "
        f"감정={float(entry.get('affective_score', 0.0)):+.2f}, "
        f"거리감={float(entry.get('distance_score', 0.5)):.2f}, "
        f"중요도={float(entry.get('importance_score', 0.0)):.2f}, "
        f"반복={entry.get('frequency_score', 1)}"
    )


def format_brain_notes(user_data: dict) -> str:
    normalize_user_memory(user_data)
    long_term = user_data[LONG_TERM_MEMORY_KEY]
    short_term = user_data[SHORT_TERM_MEMORY_KEY]

    if not long_term and not short_term:
        return "아직 저장된 기억이 없음"

    sections = []
    if long_term:
        lines = ["[장기 기억]"]
        for index, entry in enumerate(long_term, start=1):
            reason = entry.get("promotion_reason", "승격 근거 없음")
            lines.append(
                f"{index}. {entry['content']} ({_format_memory_metadata(entry)}, 근거={reason})"
            )
        sections.append("\n".join(lines))

    if short_term:
        lines = ["[단기 기억 후보]"]
        for index, entry in enumerate(short_term, start=1):
            lines.append(
                f"S{index}. {entry['content']} ({_format_memory_metadata(entry)})"
            )
        sections.append("\n".join(lines))

    return "\n\n".join(sections)


def parse_brain_index_and_note(raw_text: str) -> tuple[int | None, str]:
    parts = raw_text.strip().split(maxsplit=1)
    if not parts or not parts[0].isdigit():
        return None, ""

    index = int(parts[0])
    note = parts[1].strip() if len(parts) > 1 else ""
    return index, note
