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
- Punctuation alone is not a segmentation boundary.
- Use emotion scores from 0 to 10.
- emotion_strength must be 0.0 to 1.0.
- Use pause_after_seconds to avoid rushed joins. Prefer 0.22 to 0.36 seconds.
- Use 0.38 to 0.55 seconds when the next segment changes emotion sharply.
- Last segment may still include pause_after_seconds; the server will ignore final trailing gap.
- tts_text may add light punctuation or pauses, but must not add new facts.
- Set ending_style to flat, question, or exclaim for each segment.
- Use question only for a genuine information-seeking question that should rise at the end.
- Use flat for rhetorical questions, teasing protests, shy confessions, affectionate closings, and emotional statements.
- The last segment should usually be flat unless the speaker truly asks for an answer.
- Do not add filler words such as "그", "음", "어", or "저" unless they already exist in the original text.

Prosody continuity rules:
- Decide whether adjacent segments belong to the same spoken breath.
- Do not split greetings, names, vocatives, short acknowledgements, soft address phrases, or intimate continuations unless there is a clear semantic emotion shift.
- A comma does not imply an emotional boundary. Treat comma-connected address phrases as the same spoken breath by default.
- If two adjacent segments belong to the same breath, keep emotion and prosody continuous.
- Output continuity.carry_over from 0.0 to 0.5 for each segment:
  - 0.4 to 0.5: same breath, vocative/address phrase, intimate continuation, or the next words should feel acoustically connected.
  - 0.2 to 0.35: normal sentence-to-sentence continuity.
  - 0.05 to 0.15: clear emotional turn that should still not sound mechanically detached.
  - 0.0: hard reset, scene change, or intentionally separate delivery.
- Split only when the listener should clearly hear a change in intent, not merely because punctuation exists.
- The first segment may use carry_over 0.0 unless it is a continuation of a supplied tts_text hint.

Emotion selection rubric:
- Judge emotion from the utterance's communicative function, not from isolated words or punctuation.
- Treat punctuation, repeated marks, and short exclamations as intensity signals only. They can raise emotion_strength, but they must not decide the emotion by themselves.
- First decide whether the speaker is inviting closeness, teasing, protesting, confessing, reassuring, worrying, reacting to surprise, or grieving.
- Then assign one primary emotion and optional secondary emotions. Avoid flat averages when the segment has a clear pragmatic intent.

Emotion meanings:
- joy: warm positive feeling, gratitude, relief, delight, affectionate approval, or soft happiness.
- excited: forward-moving eagerness, anticipation, playful high energy, or delighted momentum. Do not use it for tense complaints, embarrassment, defensive speech, or scolding just because the text has "!".
- calm: steady, composed, neutral, reassuring, matter-of-fact, or gentle control.
- sad: loss, disappointment, loneliness, regret, resignation, or emotional heaviness.
- shy: embarrassment, bashfulness, vulnerable confession, indirect affection, flustered softness, or wanting closeness while feeling exposed.
- anxiety: uncertainty, fear of rejection, nervous hesitation, worry, or unstable anticipation.
- anger: frustration, reproach, protest, boundary-setting, offended teasing, or "why do I have to spell this out?" pressure.
- surprise: sudden realization, unexpected information, startled reaction, or abrupt discovery.

Conflict rules:
- High energy plus reproach, complaint, pressure, or a challenging rhetorical question should usually be anger or anxiety first, not excited.
- Affection expressed while embarrassed or defensive should usually be shy first, with joy as a secondary color.
- A confession after a tense or defensive clause should usually transition into shy/joy/calm rather than stay in anger.
- Playful teasing should stay lighter than real anger: combine shy/joy/anger only if the speech act is affectionate rather than hostile.
- If a segment mixes opposite emotions, split it into separate segments instead of averaging them.
- If the text can be read in multiple ways, choose the emotion that best explains why the speaker says it that way in context.

Schema:
{
  "segments": [
    {
      "text": "spoken segment",
      "tts_text": "optional TTS-friendly text",
      "emotion": {"calm": 6, "sad": 4},
      "emotion_strength": 0.62,
      "pause_after_seconds": 0.30,
      "ending_style": "flat",
      "continuity": {
        "mode": "same_breath | soft_transition | hard_shift | reset",
        "carry_over": 0.30,
        "reason": "short explanation"
      }
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
        raw_continuity = raw_segment.get("continuity")
        continuity = raw_continuity if isinstance(raw_continuity, dict) else {}
        continuity_mode = continuity.get("mode", raw_segment.get("continuity_mode"))
        carry_over = continuity.get("carry_over", raw_segment.get("carry_over"))
        segments.append(
            make_bandi_voice_segment(
                text or tts_text or request.display_text,
                emotion,
                emotion_strength=strength,
                tts_text=tts_text,
                pause_after_seconds=raw_segment.get("pause_after_seconds"),
                aux_limit=request.aux_limit,
                ending_style=raw_segment.get("ending_style"),
                continuity_mode=continuity_mode,
                carry_over=carry_over,
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
            ending_style=segment.ending_style,
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
        "requested_ending_style": request.ending_style,
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
