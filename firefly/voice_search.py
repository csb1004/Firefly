from dataclasses import dataclass

from .text_utils import clamp_text
from .voice_records import VoiceRecordNotFound, list_recordings, read_transcript_entries


DEFAULT_SEARCH_RECORD_LIMIT = 5
DEFAULT_SEARCH_ENTRY_LIMIT = 80


@dataclass(frozen=True)
class VoiceSearchRequest:
    query: str
    filename: str | None = None


@dataclass(frozen=True)
class VoiceSearchSelection:
    filename: str
    entries: list[dict]
    matched_count: int


def parse_voice_search_args(raw_text: str) -> VoiceSearchRequest:
    text = raw_text.strip()
    if not text:
        return VoiceSearchRequest(query="")

    first, _, rest = text.partition(" ")
    if first.endswith(".jsonl") or first.startswith("voice-"):
        return VoiceSearchRequest(query=rest.strip(), filename=first)

    return VoiceSearchRequest(query=text)


def _query_terms(query: str) -> list[str]:
    normalized = query.casefold()
    terms = []
    for raw in normalized.replace(",", " ").replace("?", " ").split():
        term = raw.strip()
        if len(term) >= 2 and term not in terms:
            terms.append(term)
    return terms


def _entry_text(entry: dict) -> str:
    return f"{entry.get('speaker_name') or ''} {entry.get('text') or ''}".casefold()


def select_relevant_voice_entries(
    entries: list[dict],
    query: str,
    *,
    limit: int = DEFAULT_SEARCH_ENTRY_LIMIT,
) -> tuple[list[dict], int]:
    terms = _query_terms(query)
    if not terms:
        return entries[-limit:], len(entries)

    scored = []
    for index, entry in enumerate(entries):
        text = _entry_text(entry)
        score = sum(1 for term in terms if term in text)
        if score:
            scored.append((score, index, entry))

    if not scored:
        return entries[-limit:], 0

    selected_indexes = set()
    for _, index, _ in scored:
        selected_indexes.update(range(max(0, index - 1), min(len(entries), index + 2)))

    selected = [entries[index] for index in sorted(selected_indexes)]
    return selected[-limit:], len(scored)


def load_voice_search_selection(
    request: VoiceSearchRequest,
    *,
    record_limit: int = DEFAULT_SEARCH_RECORD_LIMIT,
    entry_limit: int = DEFAULT_SEARCH_ENTRY_LIMIT,
) -> VoiceSearchSelection:
    if not request.query:
        raise ValueError("query is required")

    if request.filename:
        entries = read_transcript_entries(request.filename)
        selected, matched_count = select_relevant_voice_entries(
            entries,
            request.query,
            limit=entry_limit,
        )
        return VoiceSearchSelection(request.filename, selected, matched_count)

    best_selection: VoiceSearchSelection | None = None
    for record in list_recordings()[:record_limit]:
        filename = str(record.get("filename") or "")
        if not filename:
            continue
        try:
            entries = read_transcript_entries(filename)
        except VoiceRecordNotFound:
            continue

        selected, matched_count = select_relevant_voice_entries(
            entries,
            request.query,
            limit=entry_limit,
        )
        if matched_count:
            return VoiceSearchSelection(filename, selected, matched_count)
        if best_selection is None and selected:
            best_selection = VoiceSearchSelection(filename, selected, matched_count)

    if best_selection is not None:
        return best_selection

    raise VoiceRecordNotFound("latest recordings")


def format_voice_search_context(entries: list[dict]) -> str:
    lines = []
    for entry in entries:
        created_at = str(entry.get("created_at") or "").strip()
        speaker = str(entry.get("speaker_name") or "unknown").strip()
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        prefix = f"[{created_at}] " if created_at else ""
        lines.append(f"{prefix}{speaker}: {clamp_text(text, 600)}")
    return "\n".join(lines)
