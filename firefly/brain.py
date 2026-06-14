from .text_utils import clamp_text

BRAIN_NOTES_KEY = "brain_notes"
MAX_BRAIN_NOTES = 20
MAX_BRAIN_NOTE_CHARS = 400


def _normalize_note(note: object) -> str:
    return clamp_text(str(note or "").strip(), MAX_BRAIN_NOTE_CHARS)


def normalize_brain_notes(user_data: dict) -> list[str]:
    raw_notes = user_data.get(BRAIN_NOTES_KEY, [])

    if isinstance(raw_notes, str):
        raw_notes = [raw_notes] if raw_notes.strip() else []
    elif not isinstance(raw_notes, list):
        raw_notes = []

    notes = []
    for raw_note in raw_notes:
        note = _normalize_note(raw_note)
        if note:
            notes.append(note)

    notes = notes[-MAX_BRAIN_NOTES:]
    user_data[BRAIN_NOTES_KEY] = notes
    return notes


def add_brain_note(user_data: dict, note: str) -> int:
    notes = normalize_brain_notes(user_data)
    normalized_note = _normalize_note(note)
    if not normalized_note:
        raise ValueError("저장할 평가 내용이 비어 있어.")

    notes.append(normalized_note)
    notes = notes[-MAX_BRAIN_NOTES:]
    user_data[BRAIN_NOTES_KEY] = notes
    return len(notes)


def update_brain_note(user_data: dict, index: int, note: str) -> bool:
    notes = normalize_brain_notes(user_data)
    normalized_note = _normalize_note(note)
    if not normalized_note or index < 1 or index > len(notes):
        return False

    notes[index - 1] = normalized_note
    user_data[BRAIN_NOTES_KEY] = notes
    return True


def delete_brain_note(user_data: dict, index: int) -> str | None:
    notes = normalize_brain_notes(user_data)
    if index < 1 or index > len(notes):
        return None

    deleted = notes.pop(index - 1)
    user_data[BRAIN_NOTES_KEY] = notes
    return deleted


def format_brain_notes(user_data: dict) -> str:
    notes = normalize_brain_notes(user_data)
    if not notes:
        return "아직 저장된 장기 평가가 없음"
    return "\n".join(f"{index}. {note}" for index, note in enumerate(notes, start=1))


def parse_brain_index_and_note(raw_text: str) -> tuple[int | None, str]:
    parts = raw_text.strip().split(maxsplit=1)
    if not parts or not parts[0].isdigit():
        return None, ""

    index = int(parts[0])
    note = parts[1].strip() if len(parts) > 1 else ""
    return index, note
