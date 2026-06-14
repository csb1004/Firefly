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
DEFAULT_IMPORTANCE_SCORE = 0.55

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


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


def _memory_id(memory_type: str, content: str, created_at: str) -> str:
    digest = hashlib.sha1(f"{memory_type}:{created_at}:{content}".encode("utf-8")).hexdigest()[:12]
    return f"{memory_type[:2]}_{digest}"


def _importance_from_prefix(content: str) -> tuple[str, float]:
    match = re.match(
        r"^(?:중요도|importance)\s*[:=]\s*"
        r"(높음|중간|보통|낮음|high|medium|low|0(?:\.\d+)?|1(?:\.0+)?)\s+(.+)$",
        content,
        re.IGNORECASE,
    )
    if not match:
        return content, DEFAULT_IMPORTANCE_SCORE

    raw_score = match.group(1).casefold()
    cleaned = match.group(2).strip()
    score_map = {
        "높음": 0.9,
        "high": 0.9,
        "중간": 0.65,
        "보통": 0.65,
        "medium": 0.65,
        "낮음": 0.35,
        "low": 0.35,
    }
    if raw_score in score_map:
        return cleaned, score_map[raw_score]
    return cleaned, _to_score(raw_score, DEFAULT_IMPORTANCE_SCORE)


def _new_memory_entry(
    *,
    memory_type: str,
    content: str,
    importance_score: float = DEFAULT_IMPORTANCE_SCORE,
    frequency_score: int = 1,
    now: str | None = None,
    promotion_reason: str | None = None,
) -> dict:
    timestamp = now or _now_text()
    entry = {
        "memory_id": _memory_id(memory_type, content, timestamp),
        "memory_type": memory_type,
        "content": content,
        "importance_score": _to_score(importance_score, DEFAULT_IMPORTANCE_SCORE),
        "frequency_score": _to_frequency(frequency_score),
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
        "created_at": created_at,
        "updated_at": updated_at,
        "last_used_at": last_used_at,
    }
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
    def add_candidate(user_data: dict, content: str, importance_score: float) -> MemoryActionResult:
        normalize_user_memory(user_data)
        now = _now_text()
        content_key = _content_key(content)

        existing_long_term = _find_memory_by_content(user_data[LONG_TERM_MEMORY_KEY], content_key)
        if existing_long_term is not None:
            existing_long_term["frequency_score"] = _to_frequency(existing_long_term.get("frequency_score")) + 1
            existing_long_term["importance_score"] = max(
                _to_score(existing_long_term.get("importance_score"), DEFAULT_IMPORTANCE_SCORE),
                importance_score,
            )
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
            existing_short_term["importance_score"] = max(
                _to_score(existing_short_term.get("importance_score"), DEFAULT_IMPORTANCE_SCORE),
                importance_score,
            )
            existing_short_term["updated_at"] = now
            existing_short_term["last_used_at"] = now
            return MemoryManager.evaluate_candidate(user_data, existing_short_term)

        entry = _new_memory_entry(
            memory_type="short_term",
            content=content,
            importance_score=importance_score,
            now=now,
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
        content, importance_score = _importance_from_prefix(_normalize_content(raw_content))
        if not content:
            raise ValueError("저장할 평가 내용이 비어 있어.")
        return ShortTermMemoryManager.add_candidate(user_data, content, importance_score)

    @staticmethod
    def evaluate_candidate(user_data: dict, entry: dict) -> MemoryActionResult:
        reason = promotion_reason(entry)
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


def promotion_reason(entry: dict) -> str | None:
    importance_score = _to_score(entry.get("importance_score"), DEFAULT_IMPORTANCE_SCORE)
    frequency_score = _to_frequency(entry.get("frequency_score"))
    if importance_score >= PROMOTION_IMPORTANCE_THRESHOLD:
        return f"중요도 {importance_score:.2f}가 장기 기억 기준을 넘음"
    if frequency_score >= PROMOTION_FREQUENCY_THRESHOLD:
        return f"반복 등장 {frequency_score}회로 장기 기억 기준을 넘음"
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
                f"{index}. {entry['content']} "
                f"(중요도={entry['importance_score']:.2f}, 반복={entry['frequency_score']}, 근거={reason})"
            )
        sections.append("\n".join(lines))

    if short_term:
        lines = ["[단기 기억 후보]"]
        for index, entry in enumerate(short_term, start=1):
            lines.append(
                f"S{index}. {entry['content']} "
                f"(중요도={entry['importance_score']:.2f}, 반복={entry['frequency_score']})"
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
