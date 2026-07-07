import base64

import pytest

from firefly import bandi_tts
from firefly.bandi_tts import BandiVoiceError, decode_bandi_voice_response


def test_decode_bandi_voice_response_accepts_runpod_output():
    audio = b"RIFF....WAVE"
    payload = {
        "id": "runpod-job",
        "output": {
            "request_id": "hello-001",
            "content_type": "audio/wav",
            "audio_base64": base64.b64encode(audio).decode("ascii"),
            "duration_seconds": 1.75,
            "preset": "expressive",
        },
    }

    result = decode_bandi_voice_response(payload)

    assert result.audio_bytes == audio
    assert result.content_type == "audio/wav"
    assert result.duration_seconds == 1.75
    assert result.preset == "expressive"
    assert result.filename == "bandi-hello-001.wav"


def test_decode_bandi_voice_response_accepts_direct_output():
    audio = b"RIFF....WAVE"
    result = decode_bandi_voice_response(
        {
            "request_id": "direct",
            "audio_base64": base64.b64encode(audio).decode("ascii"),
        }
    )

    assert result.audio_bytes == audio
    assert result.filename == "bandi-direct.wav"


def test_decode_bandi_voice_response_reports_worker_error():
    with pytest.raises(BandiVoiceError, match="Model failed"):
        decode_bandi_voice_response({"output": {"error": "Model failed"}})


def test_direct_tts_url_does_not_reuse_runpod_api_key(monkeypatch):
    monkeypatch.setattr(bandi_tts.config, "BANDI_TTS_URL", "https://tts.example.test")
    monkeypatch.setattr(bandi_tts.config, "BANDI_TTS_API_KEY", "")
    monkeypatch.setattr(bandi_tts.config, "RUNPOD_API_KEY", "runpod-secret")

    assert bandi_tts._authorization_token() == ""
