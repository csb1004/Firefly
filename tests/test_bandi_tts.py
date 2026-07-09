import asyncio
import base64
import io
import wave

import pytest

from firefly import bandi_tts
from firefly.bandi_tts import BandiVoiceError, decode_bandi_voice_response, generate_bandi_voice, purge_runpod_queue
from firefly.bandi_voice_plan import make_bandi_voice_segment, parse_bandi_voice_command, with_segments


def _make_wav(*, frame_count: int = 10, frame_rate: int = 1000) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(frame_rate)
        writer.writeframes(b"\x01\x00" * frame_count)
    return output.getvalue()


def _wav_frame_count(audio_bytes: bytes) -> int:
    with wave.open(io.BytesIO(audio_bytes), "rb") as reader:
        return reader.getnframes()


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


def test_decode_bandi_voice_response_appends_short_wav_tail_silence():
    audio = _make_wav(frame_count=10, frame_rate=1000)

    result = decode_bandi_voice_response(
        {
            "request_id": "padded",
            "audio_base64": base64.b64encode(audio).decode("ascii"),
            "duration_seconds": 0.01,
        }
    )

    assert _wav_frame_count(result.audio_bytes) == 10 + int(
        round(1000 * bandi_tts.DEFAULT_TAIL_SILENCE_SECONDS)
    )
    assert result.duration_seconds == pytest.approx(0.01 + bandi_tts.DEFAULT_TAIL_SILENCE_SECONDS)


def test_decode_bandi_voice_response_reports_worker_error():
    with pytest.raises(BandiVoiceError, match="Model failed"):
        decode_bandi_voice_response({"output": {"error": "Model failed"}})


def test_direct_tts_url_does_not_reuse_runpod_api_key(monkeypatch):
    monkeypatch.setattr(bandi_tts.config, "BANDI_TTS_URL", "https://tts.example.test")
    monkeypatch.setattr(bandi_tts.config, "BANDI_TTS_API_KEY", "")
    monkeypatch.setattr(bandi_tts.config, "RUNPOD_API_KEY", "runpod-secret")

    assert bandi_tts._authorization_token() == ""


def test_runpod_tts_url_uses_async_run_endpoint(monkeypatch):
    monkeypatch.setattr(bandi_tts.config, "BANDI_TTS_URL", "")
    monkeypatch.setattr(bandi_tts.config, "RUNPOD_ENDPOINT_ID", "endpoint-123")

    assert bandi_tts._bandi_tts_url() == "https://api.runpod.ai/v2/endpoint-123/run"


def test_runpod_wait_timeout_uses_runpod_specific_floor(monkeypatch):
    monkeypatch.setattr(bandi_tts.config, "BANDI_TTS_URL", "")
    monkeypatch.setattr(bandi_tts.config, "RUNPOD_ENDPOINT_ID", "endpoint-123")
    monkeypatch.setattr(bandi_tts.config, "BANDI_TTS_TIMEOUT_SECONDS", 300.0)
    monkeypatch.setattr(bandi_tts.config, "RUNPOD_TTS_TIMEOUT_SECONDS", 900.0)

    assert bandi_tts._tts_wait_timeout_seconds() == 900.0


def test_direct_tts_wait_timeout_uses_bandi_timeout(monkeypatch):
    monkeypatch.setattr(bandi_tts.config, "BANDI_TTS_URL", "https://tts.example.test")
    monkeypatch.setattr(bandi_tts.config, "RUNPOD_ENDPOINT_ID", "endpoint-123")
    monkeypatch.setattr(bandi_tts.config, "BANDI_TTS_TIMEOUT_SECONDS", 300.0)
    monkeypatch.setattr(bandi_tts.config, "RUNPOD_TTS_TIMEOUT_SECONDS", 900.0)

    assert bandi_tts._tts_wait_timeout_seconds() == 300.0


def test_purge_runpod_queue_posts_to_purge_queue_endpoint(monkeypatch):
    calls = []

    def fake_request_json_sync(url, *, method, payload=None, headers=None, timeout):
        calls.append((url, method, payload, headers, timeout))
        return {"removed": 3, "status": "completed"}

    monkeypatch.setattr(bandi_tts.config, "RUNPOD_ENDPOINT_ID", "endpoint-123")
    monkeypatch.setattr(bandi_tts.config, "RUNPOD_API_KEY", "runpod-secret")
    monkeypatch.setattr(bandi_tts.config, "BANDI_TTS_TIMEOUT_SECONDS", 300.0)
    monkeypatch.setattr(bandi_tts, "_request_json_sync", fake_request_json_sync)

    result = asyncio.run(purge_runpod_queue())

    assert result == {"removed": 3, "status": "completed"}
    assert calls == [
        (
            "https://api.runpod.ai/v2/endpoint-123/purge-queue",
            "POST",
            None,
            {
                "Content-Type": "application/json",
                "Authorization": "Bearer runpod-secret",
            },
            30.0,
        )
    ]


def test_purge_runpod_queue_requires_runpod_endpoint(monkeypatch):
    monkeypatch.setattr(bandi_tts.config, "RUNPOD_ENDPOINT_ID", "")

    with pytest.raises(BandiVoiceError, match="RUNPOD_ENDPOINT_ID"):
        asyncio.run(purge_runpod_queue())


def test_generate_bandi_voice_polls_runpod_status_until_completed(monkeypatch):
    audio = b"RIFF....WAVE"
    calls = []

    def fake_post(url, payload, timeout):
        calls.append(("post", url, payload["input"]["text"]))
        return {"id": "job-123", "status": "IN_PROGRESS"}

    def fake_get(url, timeout):
        calls.append(("get", url, timeout))
        return {
            "id": "job-123",
            "status": "COMPLETED",
            "output": {
                "request_id": "voice-123",
                "audio_base64": base64.b64encode(audio).decode("ascii"),
                "content_type": "audio/wav",
            },
        }

    async def fake_sleep(seconds):
        calls.append(("sleep", seconds))

    monkeypatch.setattr(bandi_tts.config, "BANDI_TTS_URL", "")
    monkeypatch.setattr(bandi_tts.config, "RUNPOD_ENDPOINT_ID", "endpoint-123")
    monkeypatch.setattr(bandi_tts.config, "RUNPOD_API_KEY", "runpod-secret")
    monkeypatch.setattr(bandi_tts.config, "BANDI_TTS_TIMEOUT_SECONDS", 300.0)
    monkeypatch.setattr(bandi_tts, "_post_tts_request_sync", fake_post)
    monkeypatch.setattr(bandi_tts, "_get_tts_request_sync", fake_get)
    monkeypatch.setattr(bandi_tts.asyncio, "sleep", fake_sleep)

    result = asyncio.run(generate_bandi_voice("hello"))

    assert result.audio_bytes == audio
    assert result.filename == "bandi-voice-123.wav"
    assert calls[0] == ("post", "https://api.runpod.ai/v2/endpoint-123/run", "hello")
    assert calls[1][0] == "sleep"
    assert calls[2][0] == "get"
    assert calls[2][1] == "https://api.runpod.ai/v2/endpoint-123/status/job-123"


def test_wait_for_runpod_completion_timeout_mentions_job_id(monkeypatch):
    monkeypatch.setattr(bandi_tts.config, "BANDI_TTS_URL", "")
    monkeypatch.setattr(bandi_tts.config, "RUNPOD_ENDPOINT_ID", "endpoint-123")

    async def run_wait():
        loop = asyncio.get_running_loop()
        return await bandi_tts._wait_for_runpod_completion(
            {"id": "job-123", "status": "IN_PROGRESS"},
            deadline=loop.time() - 1.0,
            timeout_seconds=900.0,
        )

    with pytest.raises(BandiVoiceError, match="job_id=job-123"):
        asyncio.run(run_wait())


def test_build_request_payload_accepts_emotion_voice_request(monkeypatch):
    monkeypatch.setattr(bandi_tts.config, "BANDI_TTS_MIN_DURATION_SECONDS", 1.0)
    monkeypatch.setattr(bandi_tts.config, "BANDI_TTS_RETRY_ATTEMPTS", 3)
    request = parse_bandi_voice_command("emotion=joy:7,calm:3 strength=0.7 | good work")

    payload = bandi_tts._build_request_payload(request, "request-001")

    assert payload["input"]["request_id"] == "request-001"
    assert payload["input"]["display_text"] == "good work"
    assert payload["input"]["text"] == "good work!"
    assert payload["input"]["emotion"] == {"joy": 7.0, "calm": 3.0}
    assert payload["input"]["emotion_strength"] == 0.7
    assert payload["input"]["aux_references"] == ["joy/012.wav", "calm/168.wav"]


def test_generate_bandi_voice_sends_emotion_request_payload(monkeypatch):
    audio = base64.b64encode(b"RIFF....WAVE").decode("ascii")
    captured_payload = {}

    def fake_post(url, payload, timeout):
        captured_payload.update(payload)
        return {"output": {"request_id": "voice-123", "audio_base64": audio}}

    monkeypatch.setattr(bandi_tts.config, "BANDI_TTS_URL", "https://tts.example.test")
    monkeypatch.setattr(bandi_tts.config, "BANDI_TTS_API_KEY", "")
    monkeypatch.setattr(bandi_tts.config, "BANDI_TTS_MIN_DURATION_SECONDS", 1.0)
    monkeypatch.setattr(bandi_tts.config, "BANDI_TTS_RETRY_ATTEMPTS", 3)
    monkeypatch.setattr(bandi_tts, "_post_tts_request_sync", fake_post)

    request = parse_bandi_voice_command("emotion=joy:7,calm:3 strength=0.7 | good work")
    result = asyncio.run(generate_bandi_voice(request))

    assert result.audio_bytes == b"RIFF....WAVE"
    assert captured_payload["input"]["display_text"] == "good work"
    assert captured_payload["input"]["text"] == "good work!"
    assert captured_payload["input"]["emotion"] == {"joy": 7.0, "calm": 3.0}
    assert captured_payload["input"]["emotion_strength"] == 0.7


def test_generate_bandi_voice_sends_segment_request_payload(monkeypatch):
    audio = base64.b64encode(b"RIFF....WAVE").decode("ascii")
    captured_payload = {}

    def fake_post(url, payload, timeout):
        captured_payload.update(payload)
        return {"output": {"request_id": "voice-123", "audio_base64": audio}}

    monkeypatch.setattr(bandi_tts.config, "BANDI_TTS_URL", "https://tts.example.test")
    monkeypatch.setattr(bandi_tts.config, "BANDI_TTS_API_KEY", "")
    monkeypatch.setattr(bandi_tts, "_post_tts_request_sync", fake_post)

    request = with_segments(
        parse_bandi_voice_command("first happy then sad"),
        [
            make_bandi_voice_segment("first happy", {"joy": 8}, emotion_strength=0.7, pause_after_seconds=0.4),
            make_bandi_voice_segment("then sad", {"sad": 8}, emotion_strength=0.66),
        ],
    )
    result = asyncio.run(generate_bandi_voice(request))

    assert result.audio_bytes == b"RIFF....WAVE"
    assert captured_payload["input"]["segments"][0]["text"] == "first happy!"
    assert captured_payload["input"]["segments"][0]["pause_after_seconds"] == 0.4
    assert captured_payload["input"]["segments"][1]["text"] == "then sad."
