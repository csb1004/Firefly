from firefly.bandi_voice_plan import parse_bandi_voice_command
from firefly.bandi_voice_preprocess import SYSTEM_PROMPT, _extract_json_object, _request_from_llm_payload


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


def test_request_from_llm_payload_preserves_llm_emotion_selection():
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
    assert first_emotion == {"excited": 7.0, "joy": 5.0}
    assert second_emotion["joy"] == 7.0


def test_system_prompt_contains_general_emotion_rubric():
    assert "communicative function" in SYSTEM_PROMPT
    assert "not from isolated words or punctuation" in SYSTEM_PROMPT
    assert "High energy plus reproach" in SYSTEM_PROMPT
    assert "Affection expressed while embarrassed" in SYSTEM_PROMPT
    assert "split it into separate segments instead of averaging" in SYSTEM_PROMPT


def test_system_prompt_has_no_keyword_postprocessing_contract():
    assert "_calibrate_segment_emotion" not in SYSTEM_PROMPT
    assert "SCOLDING_PATTERNS" not in SYSTEM_PROMPT
