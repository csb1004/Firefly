from firefly.bandi_voice_plan import (
    build_runpod_input,
    format_emotion_summary,
    parse_bandi_voice_command,
    prepare_tts_text,
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
    assert payload["primary_reference"] == "neutral/168.wav"
    assert payload["aux_references"] == ["sad/020.wav", "calm/168.wav"]
    assert payload["post_filter"] == "lowpass=f=9600"


def test_format_emotion_summary_is_empty_without_plan():
    assert format_emotion_summary(parse_bandi_voice_command("상범아 수고했어")) == ""
