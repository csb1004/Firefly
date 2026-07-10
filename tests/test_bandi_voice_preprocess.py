from firefly.bandi_voice_plan import build_runpod_input, parse_bandi_voice_command
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
                    "ending_style": "flat",
                },
            ]
        },
    )

    assert planned.has_segments
    assert len(planned.segments) == 2
    assert planned.segments[0].emotion == {"joy": 8.0}
    assert planned.segments[0].pause_after_seconds == 0.44
    assert planned.segments[1].emotion == {"sad": 7.0, "calm": 3.0}
    assert planned.segments[1].ending_style == "flat"


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
                    "ending_style": "exclaim",
                }
            ]
        },
    )

    assert not planned.has_segments
    assert planned.emotion == {"joy": 7.0}
    assert planned.emotion_strength == 0.65
    assert planned.tts_text == "good work"
    assert planned.ending_style == "exclaim"


def test_request_from_llm_payload_preserves_question_ending_style():
    request = parse_bandi_voice_command("are you okay?")

    planned = _request_from_llm_payload(
        request,
        {
            "segments": [
                {
                    "text": "are you okay?",
                    "emotion": {"anxiety": 7},
                    "emotion_strength": 0.65,
                    "ending_style": "question",
                }
            ]
        },
    )

    assert planned.ending_style == "question"


def test_llm_emotion_segments_are_projected_onto_spoken_units():
    request = parse_bandi_voice_command(
        "상범아, 아침이야.\n조금만 더 눈 떠볼래?\n물 한 잔 마시고, 천천히 시작하자."
    )

    planned = _request_from_llm_payload(
        request,
        {
            "segments": [
                {
                    "text": "상범아, 아침이야.",
                    "emotion": {"calm": 8, "joy": 3},
                    "emotion_strength": 0.48,
                    "ending_style": "flat",
                },
                {
                    "text": "조금만 더 눈 떠볼래? 물 한 잔 마시고, 천천히 시작하자.",
                    "emotion": {"calm": 9, "joy": 2},
                    "emotion_strength": 0.44,
                    "ending_style": "flat",
                    "continuity": {"mode": "same_breath", "carry_over": 0.45},
                },
            ]
        },
    )

    assert [segment.display_text for segment in planned.segments] == [
        "상범아",
        "아침이야.",
        "조금만 더 눈 떠볼래?",
        "물 한 잔 마시고",
        "천천히 시작하자.",
    ]
    assert planned.segments[0].emotion == {"calm": 8.0, "joy": 3.0}
    assert planned.segments[1].emotion == {"calm": 8.0, "joy": 3.0}
    assert planned.segments[2].emotion == {"calm": 9.0, "joy": 2.0}
    assert planned.segments[3].emotion == {"calm": 9.0, "joy": 2.0}
    assert planned.segments[4].emotion == {"calm": 9.0, "joy": 2.0}
    assert planned.segments[2].ending_style == "question"
    assert planned.segments[3].ending_style == "flat"
    assert planned.segments[0].pause_after_seconds == 0.25
    assert planned.segments[3].pause_after_seconds == 0.25
    assert all(segment.continuity_mode != "same_breath" for segment in planned.segments)

    runpod_input = build_runpod_input(
        planned,
        request_id="morning-three-sentences",
        min_duration_seconds=1.0,
        retry_attempts=2,
    )
    assert runpod_input["synthesis_unit"] == "phrase"
    assert [segment["text"] for segment in runpod_input["segments"]] == [
        "상범아.",
        "아침이야.",
        "조금만 더 눈 떠볼래~?",
        "물 한 잔 마시고.",
        "천천히 시작하자.",
    ]
    assert all(segment["post_filter"] == "" for segment in runpod_input["segments"])


def test_long_comma_clauses_become_separate_synthesis_units():
    request = parse_bandi_voice_command("이리와 상범아, 꼭 안아줄게")

    planned = _request_from_llm_payload(
        request,
        {
            "segments": [
                {
                    "text": "이리와 상범아, 꼭 안아줄게",
                    "emotion": {"calm": 7, "joy": 3},
                    "emotion_strength": 0.45,
                    "continuity": {"mode": "same_breath", "carry_over": 0.45},
                }
            ]
        },
    )

    assert [segment.display_text for segment in planned.segments] == [
        "이리와 상범아",
        "꼭 안아줄게",
    ]
    assert planned.segments[0].pause_after_seconds == 0.25
    assert all(segment.continuity_mode != "same_breath" for segment in planned.segments)


def test_short_vocative_comma_gets_an_explicit_breath_pause():
    request = parse_bandi_voice_command("상범아, 아침이야.")

    planned = _request_from_llm_payload(
        request,
        {
            "segments": [
                {
                    "text": "상범아, 아침이야.",
                    "tts_text": "상범아 아침이야.",
                    "emotion": {"calm": 8, "joy": 2},
                    "emotion_strength": 0.35,
                    "continuity": {"mode": "same_breath", "carry_over": 0.44},
                }
            ]
        },
    )

    assert [segment.display_text for segment in planned.segments] == ["상범아", "아침이야."]
    assert planned.segments[0].pause_after_seconds == 0.25
    assert all(segment.continuity_mode != "same_breath" for segment in planned.segments)


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
    second_emotion = planned.segments[-1].emotion
    assert first_emotion == {"excited": 7.0, "joy": 5.0}
    assert second_emotion["joy"] == 7.0


def test_system_prompt_contains_general_emotion_rubric():
    assert "communicative function" in SYSTEM_PROMPT
    assert "not from isolated words or punctuation" in SYSTEM_PROMPT
    assert "High energy plus reproach" in SYSTEM_PROMPT
    assert "Affection expressed while embarrassed" in SYSTEM_PROMPT
    assert "split it into separate segments instead of averaging" in SYSTEM_PROMPT
    assert "Use question only for a genuine information-seeking question" in SYSTEM_PROMPT
    assert "affectionate closings" in SYSTEM_PROMPT


def test_system_prompt_has_no_keyword_postprocessing_contract():
    assert "_calibrate_segment_emotion" not in SYSTEM_PROMPT
    assert "SCOLDING_PATTERNS" not in SYSTEM_PROMPT
