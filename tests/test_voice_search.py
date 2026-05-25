import json

import pytest

from firefly import voice_search
from firefly.voice_records import VoiceRecordNotFound


def test_parse_voice_search_args_supports_filename_and_query():
    request = voice_search.parse_voice_search_args("voice-20260516.jsonl 누가 피자 얘기했어?")

    assert request.filename == "voice-20260516.jsonl"
    assert request.query == "누가 피자 얘기했어?"


def test_parse_voice_search_args_supports_recording_index_and_query():
    request = voice_search.parse_voice_search_args("1번 누가 피자 얘기했어?")

    assert request.filename == "1번"
    assert request.query == "누가 피자 얘기했어?"


def test_parse_voice_search_args_without_filename_uses_latest_records():
    request = voice_search.parse_voice_search_args("어떤 걸 먹기로 했었는지 알려줘")

    assert request.filename is None
    assert request.query == "어떤 걸 먹기로 했었는지 알려줘"


def test_select_relevant_voice_entries_matches_text_and_neighbor_context():
    entries = [
        {"speaker_name": "Alice", "text": "hello"},
        {"speaker_name": "Bob", "text": "we should eat pizza"},
        {"speaker_name": "Alice", "text": "sounds good"},
        {"speaker_name": "Bob", "text": "bye"},
    ]

    selected, matched_count = voice_search.select_relevant_voice_entries(entries, "pizza")

    assert matched_count == 1
    assert [entry["text"] for entry in selected] == [
        "hello",
        "we should eat pizza",
        "sounds good",
    ]


def test_select_relevant_voice_entries_matches_speaker_name():
    entries = [
        {"speaker_name": "Alice", "text": "hello"},
        {"speaker_name": "Bob", "text": "bye"},
    ]

    selected, matched_count = voice_search.select_relevant_voice_entries(entries, "Alice")

    assert matched_count == 1
    assert selected[0]["speaker_name"] == "Alice"


def test_load_voice_search_selection_reads_named_file(tmp_path, monkeypatch):
    record_file = tmp_path / "voice-1.jsonl"
    record_file.write_text(
        "\n".join([
            json.dumps({
                "type": "transcript",
                "created_at": "2026-05-20T12:00:00+09:00",
                "speaker": {"id": 1, "name": "Alice"},
                "text": "let us order pasta",
            }),
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(voice_search, "read_transcript_entries", lambda filename: [
        {
            "created_at": "2026-05-20T12:00:00+09:00",
            "speaker_name": "Alice",
            "text": "let us order pasta",
        }
    ])

    selection = voice_search.load_voice_search_selection(
        voice_search.VoiceSearchRequest("pasta", "voice-1.jsonl")
    )

    assert selection.filename == "voice-1.jsonl"
    assert selection.matched_count == 1


def test_load_voice_search_selection_raises_when_no_records(monkeypatch):
    monkeypatch.setattr(voice_search, "list_recordings", lambda: [])

    with pytest.raises(VoiceRecordNotFound):
        voice_search.load_voice_search_selection(voice_search.VoiceSearchRequest("pizza"))
