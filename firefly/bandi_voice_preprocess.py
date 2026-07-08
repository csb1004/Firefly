from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from openai import OpenAI

from . import config
from .bandi_voice_plan import (
    BandiVoiceCommandRequest,
    BandiVoiceSegment,
    make_bandi_voice_segment,
    with_segments,
)


client_openai = OpenAI(api_key=config.OPENAI_API_KEY)


SYSTEM_PROMPT = """
You prepare text for a Korean character voice TTS pipeline.

Return JSON only. No markdown.

Supported emotions: joy, excited, calm, sad, shy, anxiety, anger, surprise.

Rules:
- Preserve the user's meaning and spoken content.
- Split into segments only when the emotion meaningfully changes.
- Segment by sentence or clause. Do not split by individual words.
- Use 1 to 5 segments.
- Each segment must be long enough to sound natural.
- Use emotion scores from 0 to 10.
- emotion_strength must be 0.0 to 1.0.
- Use pause_after_seconds to avoid rushed joins. Prefer 0.22 to 0.36 seconds.
- Use 0.38 to 0.55 seconds when the next segment changes emotion sharply.
- Last segment may still include pause_after_seconds; the server will ignore final trailing gap.
- tts_text may add light punctuation or pauses, but must not add new facts.

Schema:
{
  "segments": [
    {
      "text": "spoken segment",
      "tts_text": "optional TTS-friendly text",
      "emotion": {"calm": 6, "sad": 4},
      "emotion_strength": 0.62,
      "pause_after_seconds": 0.30
    }
  ]
}
""".strip()


def _extract_json_object(text: str) -> dict[str, Any]:
    clean_text = text.strip()
    clean_text = re.sub(r"^```(?:json)?\s*", "", clean_text)
    clean_text = re.sub(r"\s*```$", "", clean_text)
    start = clean_text.find("{")
    end = clean_text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("voice preprocessor did not return a JSON object")
    payload = json.loads(clean_text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("voice preprocessor JSON is not an object")
    return payload


def _request_from_llm_payload(
    request: BandiVoiceCommandRequest,
    payload: dict[str, Any],
) -> BandiVoiceCommandRequest:
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list):
        return request

    segments: list[BandiVoiceSegment] = []
    for raw_segment in raw_segments:
        if not isinstance(raw_segment, dict):
            continue
        text = str(raw_segment.get("text") or "").strip()
        tts_text = str(raw_segment.get("tts_text") or "").strip() or None
        if not text and not tts_text:
            continue
        raw_emotion = raw_segment.get("emotion")
        emotion = raw_emotion if isinstance(raw_emotion, dict) else request.emotion
        raw_strength = raw_segment.get("emotion_strength")
        strength = raw_strength if raw_strength is not None else request.emotion_strength
        segments.append(
            make_bandi_voice_segment(
                text or tts_text or request.display_text,
                emotion,
                emotion_strength=strength,
                tts_text=tts_text,
                pause_after_seconds=raw_segment.get("pause_after_seconds"),
                aux_limit=request.aux_limit,
            )
        )

    if len(segments) >= 2:
        return with_segments(request, segments)
    if len(segments) == 1:
        segment = segments[0]
        return BandiVoiceCommandRequest(
            display_text=request.display_text,
            emotion=segment.emotion,
            emotion_strength=segment.emotion_strength,
            tts_text=segment.tts_text or segment.display_text,
            aux_limit=request.aux_limit,
        )
    return request


async def plan_bandi_voice_request(request: BandiVoiceCommandRequest) -> BandiVoiceCommandRequest:
    if not request.display_text.strip():
        return request

    emotion_hint = request.emotion or {}
    user_prompt = {
        "text": request.display_text,
        "tts_text": request.tts_text,
        "requested_emotion": emotion_hint,
        "requested_emotion_strength": request.emotion_strength,
    }

    try:
        response = await asyncio.to_thread(
            client_openai.responses.create,
            model=getattr(config, "BANDI_VOICE_PREPROCESS_MODEL", config.DEFAULT_MODEL),
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
            ],
        )
        payload = _extract_json_object(response.output_text)
        return _request_from_llm_payload(request, payload)
    except Exception as exc:
        print("Bandi voice preprocess error:", exc)
        return request
