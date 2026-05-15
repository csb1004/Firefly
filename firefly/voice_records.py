import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock

from .config import VOICE_RECORDING_RETENTION_DAYS, VOICE_RECORDINGS_DIR

KST = timezone(timedelta(hours=9))
INDEX_FILE = VOICE_RECORDINGS_DIR / "index.json"
RECORDS_DIR = VOICE_RECORDINGS_DIR / "records"
_LOCK = RLock()


class VoiceRecordNotFound(FileNotFoundError):
    pass


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _now_utc().isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _ensure_dirs() -> None:
    RECORDS_DIR.mkdir(parents=True, exist_ok=True)


def _load_index_unlocked() -> dict:
    if not INDEX_FILE.exists():
        return {"records": []}

    try:
        data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"records": []}

    records = data.get("records", [])
    if not isinstance(records, list):
        records = []

    records = [item for item in records if isinstance(item, dict)]
    records.sort(key=lambda item: item.get("created_at", ""))
    return {"records": records}


def _save_index_unlocked(data: dict) -> None:
    _ensure_dirs()
    temp_file = INDEX_FILE.with_name(f"{INDEX_FILE.name}.tmp")
    temp_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for attempt in range(6):
        try:
            temp_file.replace(INDEX_FILE)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.05 * (attempt + 1))


def _append_jsonl(path: Path, item: dict) -> None:
    _ensure_dirs()
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
        file.write("\n")


def _safe_filename(filename: str) -> str:
    name = Path(filename).name.strip()
    if not name:
        raise VoiceRecordNotFound(filename)
    if not name.endswith(".jsonl"):
        name = f"{name}.jsonl"
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.jsonl", name):
        raise VoiceRecordNotFound(filename)
    return name


def get_recording_path(filename: str) -> Path:
    safe_name = _safe_filename(filename)
    path = RECORDS_DIR / safe_name
    if not path.exists():
        raise VoiceRecordNotFound(filename)
    return path


def _delete_record_file_unlocked(filename: str) -> None:
    try:
        path = RECORDS_DIR / _safe_filename(filename)
    except VoiceRecordNotFound:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def purge_expired_recordings(now: datetime | None = None) -> int:
    now = now or _now_utc()
    cutoff = now - timedelta(days=VOICE_RECORDING_RETENTION_DAYS)
    removed = 0

    with _LOCK:
        data = _load_index_unlocked()
        records = data["records"]

        while records:
            created_at = _parse_datetime(records[0].get("created_at"))
            if created_at is None:
                created_at = datetime.min.replace(tzinfo=timezone.utc)
            if created_at > cutoff:
                break

            expired = records.pop(0)
            _delete_record_file_unlocked(str(expired.get("filename", "")))
            removed += 1

        if removed:
            _save_index_unlocked(data)

    return removed


def _make_filename(guild_id: int, voice_channel_id: int) -> str:
    timestamp = datetime.now(KST).strftime("%Y%m%d-%H%M%S")
    return f"voice-{timestamp}-g{guild_id}-v{voice_channel_id}.jsonl"


def create_recording(
    *,
    guild_id: int,
    guild_name: str,
    voice_channel_id: int,
    voice_channel_name: str,
    text_channel_id: int,
    text_channel_name: str,
    author_id: int,
    author_name: str,
) -> dict:
    purge_expired_recordings()

    filename = _make_filename(guild_id, voice_channel_id)
    created_at = _iso_now()
    metadata = {
        "filename": filename,
        "created_at": created_at,
        "updated_at": created_at,
        "ended_at": None,
        "status": "recording",
        "guild_id": guild_id,
        "guild_name": guild_name,
        "voice_channel_id": voice_channel_id,
        "voice_channel_name": voice_channel_name,
        "text_channel_id": text_channel_id,
        "text_channel_name": text_channel_name,
        "author_id": author_id,
        "author_name": author_name,
        "transcript_count": 0,
        "event_count": 0,
    }

    with _LOCK:
        _ensure_dirs()
        _append_jsonl(RECORDS_DIR / filename, {"type": "metadata", **metadata})

        data = _load_index_unlocked()
        data["records"].append(metadata)
        data["records"].sort(key=lambda item: item.get("created_at", ""))
        _save_index_unlocked(data)

    return metadata


def _mutate_record_unlocked(filename: str, mutator) -> dict | None:
    data = _load_index_unlocked()
    safe_name = _safe_filename(filename)

    for record in data["records"]:
        if record.get("filename") == safe_name:
            result = mutator(record)
            record["updated_at"] = _iso_now()
            _save_index_unlocked(data)
            return result if result is not None else record

    return None


def _summarize_recording_file_unlocked(filename: str) -> dict:
    safe_name = _safe_filename(filename)
    path = RECORDS_DIR / safe_name
    summary = {
        "event_count": 0,
        "transcript_count": 0,
        "status": None,
        "ended_at": None,
        "updated_at": None,
    }

    if not path.exists():
        return summary

    try:
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue

                created_at = item.get("created_at")
                if isinstance(created_at, str):
                    summary["updated_at"] = created_at

                item_type = item.get("type")
                if item_type == "event":
                    summary["event_count"] += 1
                    if item.get("event") == "recording_finished":
                        summary["status"] = "finished"
                        summary["ended_at"] = created_at
                elif item_type == "transcript":
                    summary["transcript_count"] += 1
    except OSError:
        pass

    return summary


def _apply_file_summary(record: dict) -> dict:
    filename = str(record.get("filename", ""))
    if not filename:
        return record

    summary = _summarize_recording_file_unlocked(filename)
    record["event_count"] = int(summary.get("event_count") or 0)
    record["transcript_count"] = int(summary.get("transcript_count") or 0)

    if summary.get("ended_at"):
        record["ended_at"] = summary["ended_at"]
    if summary.get("updated_at"):
        record["updated_at"] = summary["updated_at"]
    if summary.get("status") == "finished":
        record["status"] = "finished"

    return record


def append_recording_event(filename: str, event: str, **extra) -> None:
    item = {
        "type": "event",
        "created_at": _iso_now(),
        "event": event,
    }
    item.update(extra)

    with _LOCK:
        safe_name = _safe_filename(filename)
        _append_jsonl(RECORDS_DIR / safe_name, item)


def append_transcript(
    filename: str,
    *,
    speaker_id: int,
    speaker_name: str,
    text: str,
    item_id: str | None = None,
) -> None:
    text = text.strip()
    if not text:
        return

    item = {
        "type": "transcript",
        "created_at": _iso_now(),
        "speaker": {
            "id": speaker_id,
            "name": speaker_name,
        },
        "text": text,
    }
    if item_id:
        item["item_id"] = item_id

    with _LOCK:
        safe_name = _safe_filename(filename)
        _append_jsonl(RECORDS_DIR / safe_name, item)

        def mutate(record: dict) -> None:
            _apply_file_summary(record)

        _mutate_record_unlocked(safe_name, mutate)


def finish_recording(filename: str) -> dict | None:
    ended_at = _iso_now()

    with _LOCK:
        safe_name = _safe_filename(filename)
        _append_jsonl(
            RECORDS_DIR / safe_name,
            {
                "type": "event",
                "created_at": ended_at,
                "event": "recording_finished",
            },
        )

        def mutate(record: dict) -> None:
            record["status"] = "finished"
            record["ended_at"] = ended_at
            _apply_file_summary(record)

        return _mutate_record_unlocked(safe_name, mutate)


def refresh_recording_index() -> list[dict]:
    with _LOCK:
        data = _load_index_unlocked()
        for record in data["records"]:
            _apply_file_summary(record)
        _save_index_unlocked(data)
        return [dict(record) for record in data["records"]]


def list_recordings() -> list[dict]:
    purge_expired_recordings()
    with _LOCK:
        data = _load_index_unlocked()
        records = [_apply_file_summary(dict(record)) for record in data["records"]]
    records.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return records


def get_recording_metadata(filename: str) -> dict:
    purge_expired_recordings()
    safe_name = _safe_filename(filename)
    with _LOCK:
        for record in _load_index_unlocked()["records"]:
            if record.get("filename") == safe_name:
                return _apply_file_summary(dict(record))
    raise VoiceRecordNotFound(filename)


def iter_recording_items(filename: str):
    path = get_recording_path(filename)
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def read_transcript_entries(filename: str) -> list[dict]:
    entries = []
    for item in iter_recording_items(filename):
        if item.get("type") != "transcript":
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        speaker = item.get("speaker")
        if not isinstance(speaker, dict):
            speaker = {}
        entries.append({
            "created_at": item.get("created_at"),
            "speaker_id": speaker.get("id"),
            "speaker_name": speaker.get("name") or "알 수 없음",
            "text": text.strip(),
        })
    return entries


def format_recording_list(records: list[dict], limit: int = 20) -> str:
    if not records:
        return "저장된 통화 대화 파일이 없어."

    lines = []
    for index, record in enumerate(records[:limit], start=1):
        created_at = _parse_datetime(record.get("created_at"))
        if created_at:
            created_text = created_at.astimezone(KST).strftime("%Y-%m-%d %H:%M")
        else:
            created_text = "시간 알 수 없음"

        status = "기록 중" if record.get("status") == "recording" else "완료"
        transcript_count = int(record.get("transcript_count", 0))
        channel = record.get("voice_channel_name") or "알 수 없는 통화방"
        filename = record.get("filename", "unknown.jsonl")
        lines.append(
            f"{index}. `{filename}` · {created_text} · {channel} · {status} · 전사 {transcript_count}개"
        )

    if len(records) > limit:
        lines.append(f"...외 {len(records) - limit}개")

    return "\n".join(lines)
