from __future__ import annotations

import asyncio
import base64
import json
import re
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any

from . import config


class BandiVoiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class BandiVoiceResult:
    audio_bytes: bytes
    content_type: str
    duration_seconds: float | None
    preset: str | None
    request_id: str
    filename: str


def _bandi_tts_url() -> str:
    if config.BANDI_TTS_URL:
        return config.BANDI_TTS_URL
    if config.RUNPOD_ENDPOINT_ID:
        return f"https://api.runpod.ai/v2/{config.RUNPOD_ENDPOINT_ID}/runsync"
    return ""


def _authorization_token() -> str:
    if config.BANDI_TTS_URL:
        return config.BANDI_TTS_API_KEY
    return config.RUNPOD_API_KEY


def _build_request_payload(text: str, request_id: str) -> dict[str, Any]:
    return {
        "input": {
            "text": text,
            "request_id": request_id,
            "min_duration_seconds": config.BANDI_TTS_MIN_DURATION_SECONDS,
            "retry_attempts": config.BANDI_TTS_RETRY_ATTEMPTS,
        }
    }


def _safe_filename(request_id: str) -> str:
    safe_request_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", request_id).strip("-")
    return f"bandi-{(safe_request_id or 'voice')[:64]}.wav"


def _response_output(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("error"), str):
        raise BandiVoiceError(payload["error"])

    output = payload.get("output")
    if isinstance(output, dict):
        if isinstance(output.get("error"), str):
            raise BandiVoiceError(output["error"])
        return output

    if isinstance(payload.get("audio_base64"), str):
        return payload

    status = str(payload.get("status") or "").strip()
    if status and status != "COMPLETED":
        raise BandiVoiceError(f"TTS 작업이 아직 완료되지 않았어. status={status}")
    raise BandiVoiceError("TTS 응답에서 audio_base64를 찾지 못했어.")


def _decode_audio_base64(value: str) -> bytes:
    if "," in value and value.split(",", 1)[0].lower().startswith("data:"):
        value = value.split(",", 1)[1]

    try:
        audio_bytes = base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise BandiVoiceError("TTS 응답의 audio_base64를 WAV로 디코드하지 못했어.") from exc

    if not audio_bytes:
        raise BandiVoiceError("TTS 응답에 오디오 데이터가 비어 있어.")
    return audio_bytes


def decode_bandi_voice_response(payload: dict[str, Any]) -> BandiVoiceResult:
    output = _response_output(payload)
    audio_base64 = output.get("audio_base64")
    if not isinstance(audio_base64, str):
        raise BandiVoiceError("TTS 응답에서 audio_base64를 찾지 못했어.")

    request_id = str(output.get("request_id") or payload.get("id") or uuid.uuid4().hex)
    duration = output.get("duration_seconds")
    return BandiVoiceResult(
        audio_bytes=_decode_audio_base64(audio_base64),
        content_type=str(output.get("content_type") or "audio/wav"),
        duration_seconds=float(duration) if isinstance(duration, int | float) else None,
        preset=str(output.get("preset")) if output.get("preset") is not None else None,
        request_id=request_id,
        filename=_safe_filename(request_id),
    )


def _post_tts_request_sync(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    token = _authorization_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif config.RUNPOD_ENDPOINT_ID:
        raise BandiVoiceError("RUNPOD_API_KEY가 설정되지 않았어.")

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read()
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace").strip()
        clipped = error_body[:500] if error_body else exc.reason
        raise BandiVoiceError(f"TTS 서버가 HTTP {exc.code}로 응답했어: {clipped}") from exc
    except urllib.error.URLError as exc:
        raise BandiVoiceError(f"TTS 서버에 연결하지 못했어: {exc.reason}") from exc
    except TimeoutError as exc:
        raise BandiVoiceError("TTS 서버 응답 시간이 초과됐어.") from exc

    try:
        decoded = json.loads(response_body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BandiVoiceError("TTS 서버 응답이 JSON 형식이 아니야.") from exc
    if not isinstance(decoded, dict):
        raise BandiVoiceError("TTS 서버 응답이 JSON 객체가 아니야.")
    return decoded


async def generate_bandi_voice(text: str) -> BandiVoiceResult:
    clean_text = text.strip()
    if not clean_text:
        raise BandiVoiceError("음성으로 만들 문장이 비어 있어.")
    if len(clean_text) > config.BANDI_TTS_MAX_CHARS:
        raise BandiVoiceError(f"한 번에 {config.BANDI_TTS_MAX_CHARS}자까지만 음성으로 만들 수 있어.")

    url = _bandi_tts_url()
    if not url:
        raise BandiVoiceError("BANDI_TTS_URL 또는 RUNPOD_ENDPOINT_ID가 설정되지 않았어.")

    request_id = f"bandi-{uuid.uuid4().hex[:12]}"
    payload = _build_request_payload(clean_text, request_id)
    response_payload = await asyncio.to_thread(
        _post_tts_request_sync,
        url,
        payload,
        config.BANDI_TTS_TIMEOUT_SECONDS,
    )
    return decode_bandi_voice_response(response_payload)
