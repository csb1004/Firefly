from firefly.bandi_voice_plan import (
    build_runpod_input,
    make_bandi_voice_segment,
    parse_bandi_voice_command,
    with_segments,
)
from firefly.bandi_voice_preprocess import (
    SYSTEM_PROMPT,
    _request_from_llm_payload,
)


def test_make_bandi_voice_segment_defaults_carry_over_from_continuity_mode():
    segment = make_bandi_voice_segment(
        "hello, Sangbeom",
        {"calm": 6, "joy": 3},
        continuity_mode="same_breath",
    )

    assert segment.continuity_mode == "same_breath"
    assert segment.carry_over == 0.42


def test_build_runpod_input_includes_segment_continuity():
    request = with_segments(
        parse_bandi_voice_command("hello, Sangbeom"),
        [
            make_bandi_voice_segment(
                "hello, Sangbeom",
                {"calm": 6, "joy": 3},
                emotion_strength=0.45,
                continuity_mode="same_breath",
                carry_over=0.46,
            ),
            make_bandi_voice_segment(
                "I was resting quietly",
                {"calm": 7},
                emotion_strength=0.42,
                continuity_mode="soft_transition",
                carry_over=0.28,
            ),
        ],
    )

    payload = build_runpod_input(
        request,
        request_id="continuity",
        min_duration_seconds=1.0,
        retry_attempts=2,
    )

    assert payload["segments"][0]["continuity"] == {
        "mode": "same_breath",
        "carry_over": 0.46,
    }
    assert payload["segments"][1]["continuity"] == {
        "mode": "soft_transition",
        "carry_over": 0.28,
    }


def test_request_from_llm_payload_preserves_continuity_decision():
    request = parse_bandi_voice_command("hello, Sangbeom. I was resting quietly.")

    planned = _request_from_llm_payload(
        request,
        {
            "segments": [
                {
                    "text": "hello, Sangbeom.",
                    "emotion": {"calm": 6, "joy": 3},
                    "emotion_strength": 0.45,
                    "continuity": {
                        "mode": "same_breath",
                        "carry_over": 0.46,
                    },
                },
                {
                    "text": "I was resting quietly.",
                    "emotion": {"calm": 7},
                    "emotion_strength": 0.42,
                    "continuity": {
                        "mode": "soft_transition",
                        "carry_over": 0.28,
                    },
                },
            ]
        },
    )

    assert [segment.display_text for segment in planned.segments] == [
        "hello",
        "Sangbeom.",
        "I was resting quietly.",
    ]
    assert planned.segments[0].continuity_mode == "soft_transition"
    assert planned.segments[0].carry_over == 0.28
    assert planned.segments[1].continuity_mode == "soft_transition"
    assert planned.segments[1].carry_over == 0.28
    assert planned.segments[2].continuity_mode == "soft_transition"
    assert planned.segments[2].carry_over == 0.28


def test_single_llm_emotion_annotation_keeps_punctuation_acoustic_boundaries():
    request = parse_bandi_voice_command("hello. Sangbeom.")

    planned = _request_from_llm_payload(
        request,
        {
            "segments": [
                {
                    "text": "hello. Sangbeom.",
                    "tts_text": "hello Sangbeom.",
                    "emotion": {"calm": 7, "joy": 2},
                    "emotion_strength": 0.34,
                    "continuity": {
                        "mode": "same_breath",
                        "carry_over": 0.45,
                    },
                }
            ]
        },
    )

    assert [segment.display_text for segment in planned.segments] == ["hello.", "Sangbeom."]
    assert all(segment.continuity_mode == "soft_transition" for segment in planned.segments)
    assert all(segment.carry_over == 0.28 for segment in planned.segments)


def test_build_runpod_input_includes_normalized_phrase_continuity():
    request = _request_from_llm_payload(
        parse_bandi_voice_command("hello. Sangbeom."),
        {
            "segments": [
                {
                    "text": "hello. Sangbeom.",
                    "tts_text": "hello Sangbeom.",
                    "emotion": {"calm": 7, "joy": 2},
                    "emotion_strength": 0.34,
                    "continuity": {
                        "mode": "same_breath",
                        "carry_over": 0.45,
                    },
                }
            ]
        },
    )

    payload = build_runpod_input(
        request,
        request_id="single-continuity",
        min_duration_seconds=1.0,
        retry_attempts=2,
    )

    assert [segment["text"] for segment in payload["segments"]] == ["hello.", "Sangbeom."]
    assert all(
        segment["continuity"] == {"mode": "soft_transition", "carry_over": 0.28}
        for segment in payload["segments"]
    )


def test_system_prompt_requests_general_prosody_continuity():
    assert "Prosody continuity rules" in SYSTEM_PROMPT
    assert "Punctuation alone is not a segmentation boundary" in SYSTEM_PROMPT
    assert "may create an acoustic boundary" in SYSTEM_PROMPT
    assert "Do not merge punctuation-separated phrases" in SYSTEM_PROMPT
    assert "continuity.carry_over" in SYSTEM_PROMPT
    assert "same_breath | soft_transition | hard_shift | reset" in SYSTEM_PROMPT
