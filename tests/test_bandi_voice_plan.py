from firefly.bandi_voice_plan import (
    build_runpod_input,
    format_emotion_summary,
    make_bandi_voice_segment,
    parse_bandi_voice_command,
    prepare_tts_text,
    with_segments,
)


def test_parse_bandi_voice_command_accepts_emotion_mix_prefix():
    request = parse_bandi_voice_command("감정=기쁨:7,슬픔:3 강도=0.7 | 상범아 수고했어")

    assert request.display_text == "상범아 수고했어"
    assert request.emotion == {"joy": 7.0, "sad": 3.0}
    assert request.emotion_strength == 0.7


def test_parse_bandi_voice_command_accepts_leading_shorthand():
    request = parse_bandi_voice_command("기쁨7 차분3 상범아 수고했어")

    assert request.display_text == "상범아 수고했어"
    assert request.emotion == {"joy": 7.0, "calm": 3.0}
    assert request.emotion_strength > 0.6


def test_prepare_tts_text_repairs_punctuation_for_emotion():
    assert prepare_tts_text("상범아 수고했어", {"joy": 7}) == "상범아 수고했어!"
    assert prepare_tts_text("오늘은 조금 마음이 무거워", {"sad": 7}) == "오늘은 조금... 마음이 무거워."


def test_prepare_tts_text_does_not_insert_shy_filler_word():
    assert prepare_tts_text("상범아 고마워", {"shy": 7}) == "상범아, 고마워."


def test_prepare_tts_text_avoids_unintended_rising_question_ending():
    assert prepare_tts_text("사랑해 상범아", {"anxiety": 7}) == "사랑해 상범아."
    assert prepare_tts_text("사랑해 상범아?", {"shy": 6, "anxiety": 4}) == "사랑해 상범아."


def test_prepare_tts_text_preserves_explicit_question_ending_style():
    assert (
        prepare_tts_text("괜찮아?", {"anxiety": 7}, ending_style="question")
        == "괜찮아?"
    )


def test_prepare_tts_text_focuses_bollae_question_rise_on_final_syllable():
    assert (
        prepare_tts_text("조금만 더 눈 떠볼래?", {"calm": 7}, ending_style="question")
        == "조금만 더 눈 떠볼, 래~?"
    )


def test_prepare_tts_text_keeps_non_bollae_question_joined():
    assert prepare_tts_text("같이 갈래?", {"calm": 7}, ending_style="question") == "같이 갈래?"


def test_build_runpod_input_adds_reference_mix_fields():
    request = parse_bandi_voice_command("emotion=sad:7,calm:3 strength=0.72 | 오늘은 조금 마음이 무거워")

    payload = build_runpod_input(
        request,
        request_id="sample",
        min_duration_seconds=1.0,
        retry_attempts=3,
    )

    assert payload["request_id"] == "sample"
    assert payload["display_text"] == "오늘은 조금 마음이 무거워"
    assert payload["text"] == "오늘은 조금... 마음이 무거워."
    assert payload["emotion"] == {"sad": 7.0, "calm": 3.0}
    assert payload["emotion_strength"] == 0.72
    assert payload["ending_style"] == "flat"
    assert payload["primary_reference"] == "neutral/168.wav"
    assert payload["aux_references"] == ["sad/020.wav", "calm/168.wav"]
    assert payload["post_filter"] == "lowpass=f=9600"


def test_format_emotion_summary_is_empty_without_plan():
    assert format_emotion_summary(parse_bandi_voice_command("상범아 수고했어")) == ""


def test_build_runpod_input_adds_segment_payloads():
    request = with_segments(
        parse_bandi_voice_command("good work, but I feel sad"),
        [
            make_bandi_voice_segment("good work", {"joy": 8}, emotion_strength=0.7, pause_after_seconds=0.42),
            make_bandi_voice_segment("but I feel sad", {"sad": 7, "calm": 3}, emotion_strength=0.62),
        ],
    )

    payload = build_runpod_input(
        request,
        request_id="segmented",
        min_duration_seconds=1.0,
        retry_attempts=2,
    )

    assert payload["request_id"] == "segmented"
    assert payload["segments"][0]["text"] == "good work!"
    assert payload["segments"][0]["ending_style"] == "flat"
    assert payload["segments"][0]["emotion"] == {"joy": 8.0}
    assert payload["segments"][0]["pause_after_seconds"] == 0.42
    assert payload["segments"][1]["text"] == "but I feel sad."
    assert payload["segments"][1]["emotion"] == {"sad": 7.0, "calm": 3.0}
    assert payload["segments"][1]["pause_after_seconds"] == 0.26
    assert payload["segment_gap_seconds"] == 0.26


def test_build_runpod_input_skips_post_filter_for_soft_expression():
    request = parse_bandi_voice_command("emotion=joy:4,calm:6 strength=0.35 | good morning")

    payload = build_runpod_input(
        request,
        request_id="soft",
        min_duration_seconds=1.0,
        retry_attempts=2,
    )

    assert payload["post_filter"] == ""


def test_build_runpod_input_skips_segment_post_filter_for_soft_expression():
    request = with_segments(
        parse_bandi_voice_command("good morning, rest easy"),
        [
            make_bandi_voice_segment(
                "good morning",
                {"joy": 4, "calm": 6},
                emotion_strength=0.35,
            ),
            make_bandi_voice_segment(
                "rest easy",
                {"calm": 8, "joy": 2},
                emotion_strength=0.32,
                pause_after_seconds=0.34,
            ),
        ],
    )

    payload = build_runpod_input(
        request,
        request_id="soft-segment",
        min_duration_seconds=1.0,
        retry_attempts=2,
    )

    assert payload["segments"][0]["post_filter"] == ""
    assert payload["segments"][1]["post_filter"] == ""
    assert payload["segments"][1]["pause_after_seconds"] == 0.34


def test_build_runpod_input_includes_speech_rate_hint():
    request = parse_bandi_voice_command("상범아 좋은 아침이야")

    payload = build_runpod_input(
        request,
        request_id="speed",
        min_duration_seconds=1.0,
        retry_attempts=2,
        speech_rate=1.05,
    )

    assert payload["speech_rate"] == 1.05


def test_build_runpod_input_keeps_segment_question_only_when_requested():
    request = with_segments(
        parse_bandi_voice_command("maybe worried, then ask"),
        [
            make_bandi_voice_segment("I am worried", {"anxiety": 8}, emotion_strength=0.7),
            make_bandi_voice_segment(
                "Are you okay?",
                {"anxiety": 7},
                emotion_strength=0.65,
                ending_style="question",
            ),
        ],
    )

    payload = build_runpod_input(
        request,
        request_id="questions",
        min_duration_seconds=1.0,
        retry_attempts=2,
    )

    assert payload["segments"][0]["text"] == "I am worried."
    assert payload["segments"][0]["ending_style"] == "flat"
    assert payload["segments"][1]["text"] == "Are you okay?"
    assert payload["segments"][1]["ending_style"] == "question"


def test_format_emotion_summary_includes_segment_emotion_line():
    request = with_segments(
        parse_bandi_voice_command("good work, but I feel sad"),
        [
            make_bandi_voice_segment("good work", {"joy": 8}, emotion_strength=0.7),
            make_bandi_voice_segment("but I feel sad", {"sad": 7, "calm": 3}, emotion_strength=0.62),
        ],
    )

    assert format_emotion_summary(request) == " 구간=2개, 감정선=joy:8 -> sad:7/calm:3"
