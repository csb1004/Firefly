from __future__ import annotations

import asyncio
from dataclasses import dataclass
from difflib import SequenceMatcher
import json
import re
from typing import Any

from openai import OpenAI

from . import config
from .bandi_voice_plan import (
    BandiVoiceCommandRequest,
    BandiVoiceSegment,
    DEFAULT_SEGMENT_PAUSE_SECONDS,
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
- Treat segments as emotion annotations. The application will choose phrase-level acoustic boundaries.
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
- If the whole utterance is a short greeting plus an address/vocative phrase, keep it as one segment even if the user typed a comma or period between them.
- For same_breath greeting/address phrases, set tts_text to a smooth single-breath form by replacing hard internal punctuation with a space. Preserve the original words.
- For short same_breath greeting/address phrases, prefer calm as the primary emotion, optional low joy as a secondary color, and a low-to-moderate emotion_strength around 0.25 to 0.40 unless the text clearly demands stronger emotion.
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


CLAUSE_PAUSE_SECONDS = 0.34


@dataclass(frozen=True)
class _SpokenUnit:
    text: str
    pause_after_seconds: float | None = None
    follows_clause_break: bool = False


def _split_comma_clauses(sentence: str) -> list[_SpokenUnit]:
    pieces = [piece.strip() for piece in sentence.split(",") if piece.strip()]
    if len(pieces) <= 1:
        return [_SpokenUnit(sentence.strip())]
    return [
        _SpokenUnit(
            piece,
            CLAUSE_PAUSE_SECONDS if index < len(pieces) - 1 else None,
            follows_clause_break=index > 0,
        )
        for index, piece in enumerate(pieces)
    ]


def _split_spoken_units(text: str) -> list[_SpokenUnit]:
    """Return stable sentence or breath-sized phrase synthesis units."""
    clean_text = str(text or "").strip()
    if not clean_text:
        return []
    sentences = [
        match.group(0).strip()
        for match in re.finditer(r"[^.!?~\n]+(?:[.!?~]+|(?=\n|$))", clean_text)
        if match.group(0).strip()
    ]
    if not sentences:
        sentences = [clean_text]

    units = []
    for sentence in sentences:
        units.extend(_split_comma_clauses(sentence))
    return units


def _alignment_text(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", str(text or "")).lower()


def _best_annotation_indexes(
    units: list[str],
    annotations: list[BandiVoiceSegment],
) -> list[int]:
    if len(annotations) == 1:
        return [0] * len(units)

    indexes = []
    for unit_index, unit in enumerate(units):
        unit_key = _alignment_text(unit)
        expected = round(unit_index * (len(annotations) - 1) / max(len(units) - 1, 1))
        scored = []
        for annotation_index, annotation in enumerate(annotations):
            annotation_key = _alignment_text(annotation.display_text)
            score = SequenceMatcher(None, unit_key, annotation_key).ratio()
            if unit_key and annotation_key and (
                unit_key in annotation_key or annotation_key in unit_key
            ):
                score += 1.0
            scored.append((score, -abs(annotation_index - expected), -annotation_index))
        indexes.append(max(range(len(scored)), key=scored.__getitem__))
    return indexes


def _unit_ending_style(unit: str, annotation: BandiVoiceSegment) -> str:
    stripped = unit.rstrip()
    if stripped.endswith("?"):
        return "question"
    if stripped.endswith("!"):
        return "exclaim"
    return annotation.ending_style if annotation.ending_style != "question" else "flat"


def _project_annotations_to_spoken_units(
    request: BandiVoiceCommandRequest,
    annotations: list[BandiVoiceSegment],
) -> list[BandiVoiceSegment]:
    spoken_units = _split_spoken_units(request.display_text)
    if len(spoken_units) <= 1 or not annotations:
        return annotations
    if (
        len(annotations) == 1
        and annotations[0].continuity_mode == "same_breath"
        and annotations[0].tts_text
        and not any(unit.follows_clause_break for unit in spoken_units)
    ):
        return annotations

    unit_texts = [unit.text for unit in spoken_units]
    annotation_indexes = _best_annotation_indexes(unit_texts, annotations)
    usage_counts = {
        index: annotation_indexes.count(index)
        for index in set(annotation_indexes)
    }
    projected = []
    for unit, annotation_index in zip(spoken_units, annotation_indexes):
        annotation = annotations[annotation_index]
        annotation_is_shared = usage_counts[annotation_index] > 1
        continuity_mode = annotation.continuity_mode
        if annotation_is_shared and continuity_mode == "same_breath":
            continuity_mode = "soft_transition"
        projected.append(
            make_bandi_voice_segment(
                unit.text,
                annotation.emotion,
                emotion_strength=annotation.emotion_strength,
                tts_text=annotation.tts_text if usage_counts[annotation_index] == 1 else None,
                pause_after_seconds=(
                    (
                        max(unit.pause_after_seconds, annotation.pause_after_seconds)
                        if annotation.pause_after_seconds > DEFAULT_SEGMENT_PAUSE_SECONDS
                        else unit.pause_after_seconds
                    )
                    if unit.pause_after_seconds is not None
                    else annotation.pause_after_seconds
                ),
                aux_limit=annotation.aux_limit,
                ending_style=_unit_ending_style(unit.text, annotation),
                continuity_mode=continuity_mode,
                carry_over=(
                    min(annotation.carry_over, 0.28)
                    if annotation_is_shared
                    else annotation.carry_over
                ),
            )
        )
    return projected


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

    projected_segments = _project_annotations_to_spoken_units(request, segments)
    if len(projected_segments) >= 2:
        return with_segments(request, projected_segments)
    if len(projected_segments) == 1:
        segment = projected_segments[0]
        return BandiVoiceCommandRequest(
            display_text=request.display_text,
            emotion=segment.emotion,
            emotion_strength=segment.emotion_strength,
            tts_text=segment.tts_text or segment.display_text,
            aux_limit=request.aux_limit,
            ending_style=segment.ending_style,
            continuity_mode=segment.continuity_mode,
            carry_over=segment.carry_over,
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
