from firefly.bandi_voice_plan import parse_bandi_voice_command
from firefly.bandi_voice_preprocess import _extract_json_object, _request_from_llm_payload


def test_extract_json_object_accepts_fenced_json():
    payload = _extract_json_object('```json\n{"segments": []}\n```')

    assert payload == {"segments": []}


def test_request_from_llm_payload_builds_voice_segments():
    request = parse_bandi_voice_command("I am happy, but then I felt sad")

    planned = _request_from_llm_payload(
        request,
        {
            "segments": [
                {
                    "text": "I am happy.",
                    "emotion": {"joy": 8},
                    "emotion_strength": 0.72,
                    "pause_after_seconds": 0.44,
                },
                {
                    "text": "But then I felt sad.",
                    "emotion": {"sad": 7, "calm": 3},
                    "emotion_strength": 0.62,
                    "pause_after_seconds": 0.3,
                },
            ]
        },
    )

    assert planned.has_segments
    assert len(planned.segments) == 2
    assert planned.segments[0].emotion == {"joy": 8.0}
    assert planned.segments[0].pause_after_seconds == 0.44
    assert planned.segments[1].emotion == {"sad": 7.0, "calm": 3.0}


def test_request_from_llm_payload_uses_single_segment_as_emotion_plan():
    request = parse_bandi_voice_command("good work")

    planned = _request_from_llm_payload(
        request,
        {
            "segments": [
                {
                    "text": "good work",
                    "emotion": {"joy": 7},
                    "emotion_strength": 0.65,
                }
            ]
        },
    )

    assert not planned.has_segments
    assert planned.emotion == {"joy": 7.0}
    assert planned.emotion_strength == 0.65
    assert planned.tts_text == "good work"


def test_request_from_llm_payload_calibrates_embarrassed_scolding():
    request = parse_bandi_voice_command("정말! 부끄럽게 꼭 말해야 아는거야? ..사랑해 상범아.")

    planned = _request_from_llm_payload(
        request,
        {
            "segments": [
                {
                    "text": "정말! 부끄럽게 꼭 말해야 아는거야?",
                    "emotion": {"excited": 7, "joy": 5},
                    "emotion_strength": 0.7,
                },
                {
                    "text": "..사랑해 상범아.",
                    "emotion": {"joy": 7},
                    "emotion_strength": 0.65,
                },
            ]
        },
    )

    first_emotion = planned.segments[0].emotion
    second_emotion = planned.segments[1].emotion
    assert first_emotion["anger"] == 6.0
    assert first_emotion["shy"] == 5.0
    assert first_emotion["excited"] == 1.0
    assert first_emotion["joy"] == 1.0
    assert second_emotion["shy"] == 6.0
    assert second_emotion["joy"] == 7.0
    assert second_emotion.get("excited", 0.0) <= 1.0


def test_request_from_llm_payload_respects_explicit_emotion_request():
    request = parse_bandi_voice_command("emotion=joy:8 | 정말! 부끄럽게 꼭 말해야 아는거야?")

    planned = _request_from_llm_payload(
        request,
        {
            "segments": [
                {
                    "text": "정말! 부끄럽게 꼭 말해야 아는거야?",
                    "emotion": {"joy": 8},
                    "emotion_strength": 0.7,
                }
            ]
        },
    )

    assert planned.emotion == {"joy": 8.0}
