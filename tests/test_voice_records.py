import pytest

from firefly.voice_records import (
    VoiceRecordNotFound,
    parse_recording_index_reference,
    resolve_recording_reference,
)


def test_parse_recording_index_reference_requires_marker_by_default():
    assert parse_recording_index_reference("1") is None
    assert parse_recording_index_reference("1", allow_plain_index=True) == 1
    assert parse_recording_index_reference("1번") == 1
    assert parse_recording_index_reference("#2") == 2
    assert parse_recording_index_reference("index:3") == 3


def test_resolve_recording_reference_uses_recent_list_order():
    records = [
        {"filename": "voice-new.jsonl"},
        {"filename": "voice-old.jsonl"},
    ]

    assert resolve_recording_reference("1번", records=records) == "voice-new.jsonl"
    assert resolve_recording_reference("#2", records=records) == "voice-old.jsonl"
    assert resolve_recording_reference("voice-direct.jsonl", records=records) == "voice-direct.jsonl"


def test_resolve_recording_reference_raises_for_missing_index():
    with pytest.raises(VoiceRecordNotFound):
        resolve_recording_reference("3번", records=[{"filename": "voice-new.jsonl"}])
