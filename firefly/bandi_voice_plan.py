from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


class BandiVoicePlanError(ValueError):
    pass


SUPPORTED_EMOTIONS = {
    "joy",
    "excited",
    "calm",
    "sad",
    "shy",
    "anxiety",
    "anger",
    "surprise",
}

EMOTION_ALIASES = {
    "joy": "joy",
    "happy": "joy",
    "happiness": "joy",
    "기쁨": "joy",
    "즐거움": "joy",
    "행복": "joy",
    "excited": "excited",
    "excitement": "excited",
    "고조": "excited",
    "흥분": "excited",
    "신남": "excited",
    "calm": "calm",
    "차분": "calm",
    "평온": "calm",
    "안정": "calm",
    "sad": "sad",
    "sadness": "sad",
    "슬픔": "sad",
    "우울": "sad",
    "shy": "shy",
    "부끄러움": "shy",
    "수줍음": "shy",
    "anxiety": "anxiety",
    "anxious": "anxiety",
    "불안": "anxiety",
    "걱정": "anxiety",
    "anger": "anger",
    "angry": "anger",
    "화남": "anger",
    "분노": "anger",
    "surprise": "surprise",
    "surprised": "surprise",
    "놀람": "surprise",
}

DEFAULT_REFERENCE_CANDIDATES = {
    "joy": ["012.wav"],
    "excited": ["312.wav"],
    "calm": ["168.wav"],
    "sad": ["020.wav"],
    "shy": ["249.wav"],
    "anxiety": ["004.wav"],
    "anger": ["003.wav"],
    "surprise": ["180.wav"],
}

DEFAULT_PRIMARY_REFERENCE = "neutral/168.wav"
DEFAULT_SEGMENT_PAUSE_SECONDS = 0.26
MIN_SEGMENT_PAUSE_SECONDS = 0.16
MAX_SEGMENT_PAUSE_SECONDS = 0.75
MAX_VOICE_SEGMENTS = 5
DEFAULT_PROSODY_CARRY_OVER = 0.24
MAX_PROSODY_CARRY_OVER = 0.5

LOWPASS_BY_EMOTION = {
    "joy": 10600,
    "excited": 10400,
    "sad": 9600,
    "anxiety": 9800,
    "anger": 10000,
}

OPTION_KEYS = {
    "emotion",
    "emotions",
    "감정",
    "voice",
    "mood",
    "strength",
    "emotion_strength",
    "강도",
    "표현강도",
    "tts",
    "tts_text",
    "ending_style",
    "intonation",
    "끝억양",
    "억양",
}


@dataclass(frozen=True)
class BandiVoiceSegment:
    display_text: str
    emotion: dict[str, float]
    emotion_strength: float
    tts_text: str | None = None
    pause_after_seconds: float = DEFAULT_SEGMENT_PAUSE_SECONDS
    aux_limit: int = 3
    ending_style: str = "flat"
    continuity_mode: str = "normal"
    carry_over: float = DEFAULT_PROSODY_CARRY_OVER


@dataclass(frozen=True)
class BandiVoiceCommandRequest:
    display_text: str
    emotion: dict[str, float]
    emotion_strength: float
    tts_text: str | None = None
    aux_limit: int = 3
    ending_style: str = "flat"
    segments: tuple[BandiVoiceSegment, ...] = ()

    @property
    def has_emotion_plan(self) -> bool:
        return bool(self.emotion or self.segments)

    @property
    def has_segments(self) -> bool:
        return bool(self.segments)


def clamp_float(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def normalize_emotion_name(value: str) -> str | None:
    key = value.strip().lower().replace("-", "_")
    if key in SUPPORTED_EMOTIONS:
        return key
    return EMOTION_ALIASES.get(key)


def normalize_emotion_scores(raw_emotion: dict[str, float]) -> dict[str, float]:
    scores = {}
    for name, value in raw_emotion.items():
        normalized_name = normalize_emotion_name(str(name))
        if normalized_name is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            scores[normalized_name] = scores.get(normalized_name, 0.0) + clamp_float(number, 0.0, 10.0)
    return scores


def normalize_emotion_weights(raw_emotion: dict[str, float]) -> dict[str, float]:
    weighted = {}
    for name, value in raw_emotion.items():
        normalized_name = normalize_emotion_name(str(name))
        if normalized_name is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            weighted[normalized_name] = weighted.get(normalized_name, 0.0) + number

    total = sum(weighted.values())
    if total <= 0:
        return {}
    return {name: value / total for name, value in weighted.items()}


def clean_punctuation(text: str) -> str:
    text = str(text).replace("…", "...")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\.{4,}", "...", text)
    text = re.sub(r"!{2,}", "!", text)
    text = re.sub(r"\?{2,}", "?", text)
    text = re.sub(r"\?!+", "?!", text)
    text = re.sub(r"!\?+", "!?", text)
    text = re.sub(r"\s+([,.?!~])", r"\1", text)
    text = re.sub(r"([,.?!~])(?=[^\s,.?!~])", r"\1 ", text)
    return text.strip()


def normalize_ending_style(value: object) -> str:
    style = re.sub(r"[\s_\-]+", "", str(value or "flat").strip().lower())
    if style in {"question", "questionintonation", "rising", "rise", "물음", "질문", "질문형"}:
        return "question"
    if style in {"excited", "exclaim", "exclamation", "감탄", "감탄형"}:
        return "exclaim"
    return "flat"


def normalize_continuity_mode(value: object) -> str:
    mode = re.sub(r"[\s\-]+", "_", str(value or "normal").strip().lower())
    if mode in {"same_breath", "samebreath", "breath", "continuation", "vocative", "address", "intimate"}:
        return "same_breath"
    if mode in {"soft_transition", "soft", "connected", "normal"}:
        return "soft_transition"
    if mode in {"hard_shift", "hard", "turn", "contrast"}:
        return "hard_shift"
    if mode in {"reset", "scene_reset", "new_scene"}:
        return "reset"
    return "normal"


def default_carry_over_for_mode(mode: str) -> float:
    normalized_mode = normalize_continuity_mode(mode)
    if normalized_mode == "same_breath":
        return 0.42
    if normalized_mode == "soft_transition":
        return 0.28
    if normalized_mode == "hard_shift":
        return 0.1
    if normalized_mode == "reset":
        return 0.0
    return DEFAULT_PROSODY_CARRY_OVER


def normalize_carry_over(value: object, *, continuity_mode: object = "normal") -> float:
    if value is None:
        return default_carry_over_for_mode(str(continuity_mode or "normal"))
    try:
        carry_over = float(value)
    except (TypeError, ValueError):
        carry_over = default_carry_over_for_mode(str(continuity_mode or "normal"))
    return round(clamp_float(carry_over, 0.0, MAX_PROSODY_CARRY_OVER), 3)


def soften_terminal_question(text: str, ending_style: str) -> str:
    if normalize_ending_style(ending_style) == "question":
        return text
    return re.sub(r"\?+$", ".", text.strip())


def ensure_sentence_ending(
    text: str,
    emotion_weights: dict[str, float],
    ending_style: str = "flat",
) -> str:
    if not text:
        return text
    if text[-1] in ".?!~":
        return text
    normalized_ending = normalize_ending_style(ending_style)
    if normalized_ending == "question":
        return f"{text}?"
    if normalized_ending == "exclaim":
        return f"{text}!"
    top_emotion = max(emotion_weights, key=emotion_weights.get, default="")
    if top_emotion in {"joy", "excited"}:
        return f"{text}!"
    return f"{text}."


def apply_emotion_tts_pauses(text: str, emotion_weights: dict[str, float]) -> str:
    if emotion_weights.get("sad", 0.0) >= 0.35:
        text = re.sub(r"^상범아\s+", "상범아, ", text)
        text = re.sub(r"조금[\s,.]*마음이", "조금... 마음이", text)
    if emotion_weights.get("shy", 0.0) >= 0.45:
        text = re.sub(r"^상범아(?:\s+|,\s*)", "상범아, ", text)
    return text


def prepare_tts_text(
    display_text: str,
    emotion: dict[str, float],
    proposed_tts_text: str | None = None,
    ending_style: str = "flat",
) -> str:
    emotion_weights = normalize_emotion_weights(emotion)
    text = proposed_tts_text if proposed_tts_text else display_text
    text = clean_punctuation(text)
    text = apply_emotion_tts_pauses(text, emotion_weights)
    text = clean_punctuation(text)
    text = ensure_sentence_ending(text, emotion_weights, ending_style)
    return soften_terminal_question(text, ending_style)


def choose_aux_references(
    emotion: dict[str, float],
    reference_candidates: dict[str, list[str]] | None = None,
    *,
    max_refs: int = 3,
    min_weight: float = 0.08,
) -> list[str]:
    candidates = reference_candidates or DEFAULT_REFERENCE_CANDIDATES
    emotion_weights = normalize_emotion_weights(emotion)
    refs = []
    for name, weight in sorted(emotion_weights.items(), key=lambda item: item[1], reverse=True):
        if weight < min_weight:
            continue
        filenames = candidates.get(name, [])
        if filenames:
            refs.append(f"{name}/{filenames[0]}")
        if len(refs) >= max_refs:
            break
    return refs


def choose_post_filter(emotion: dict[str, float], *, min_weight: float = 0.12) -> str:
    emotion_weights = normalize_emotion_weights(emotion)
    cutoffs = [
        LOWPASS_BY_EMOTION[name]
        for name, weight in emotion_weights.items()
        if weight >= min_weight and name in LOWPASS_BY_EMOTION
    ]
    if not cutoffs:
        return ""
    return f"lowpass=f={min(cutoffs)}"


def _has_option_hint(text: str) -> bool:
    lower = text.lower()
    if any(f"{key}=" in lower or f"{key}:" in lower for key in OPTION_KEYS):
        return True
    return any(_parse_emotion_token(token) is not None for token in text.split())


def _split_option_prefix(raw_text: str) -> tuple[str, str]:
    for separator in ("|", "\n"):
        if separator in raw_text:
            option_text, display_text = raw_text.split(separator, 1)
            if _has_option_hint(option_text):
                return option_text.strip(), display_text.strip()

    tokens = raw_text.split()
    option_tokens = []
    while tokens:
        token = tokens[0]
        if _is_option_token(token):
            option_tokens.append(tokens.pop(0))
            continue
        break
    if option_tokens:
        return " ".join(option_tokens), " ".join(tokens).strip()
    return "", raw_text.strip()


def _is_option_token(token: str) -> bool:
    if "=" in token or ":" in token:
        key = token.split("=", 1)[0].split(":", 1)[0].strip().lower()
        return key in OPTION_KEYS or normalize_emotion_name(key) is not None
    return _parse_emotion_token(token) is not None


def _parse_emotion_token(token: str) -> tuple[str, float] | None:
    token = token.strip().strip(",")
    if not token:
        return None
    match = re.fullmatch(r"([A-Za-z가-힣_]+)(?:[:=]?(\d+(?:\.\d+)?))?", token)
    if not match:
        return None
    emotion_name = normalize_emotion_name(match.group(1))
    if emotion_name is None:
        return None
    score = float(match.group(2)) if match.group(2) else 7.0
    return emotion_name, clamp_float(score, 0.0, 10.0)


def _parse_emotion_items(raw_value: str) -> dict[str, float]:
    emotion: dict[str, float] = {}
    for item in re.split(r"[,/]+", raw_value):
        item = item.strip()
        if not item:
            continue
        parsed = _parse_emotion_token(item)
        if parsed is None and ":" not in item and "=" not in item:
            parsed = (normalize_emotion_name(item) or "", 7.0)
        if parsed is None:
            continue
        name, score = parsed
        if name:
            emotion[name] = emotion.get(name, 0.0) + score
    return emotion


def _parse_strength(raw_value: str) -> float:
    value = float(raw_value)
    if value > 1.0:
        value = value / 10.0
    return clamp_float(value, 0.0, 1.0)


def _derive_strength(emotion: dict[str, float]) -> float:
    if not emotion:
        return 0.0
    max_score = max(emotion.values())
    return round(clamp_float(0.42 + (max_score / 10.0) * 0.4, 0.45, 0.82), 3)


def normalize_segment_pause(value: float | int | str | None) -> float:
    if value is None:
        return DEFAULT_SEGMENT_PAUSE_SECONDS
    try:
        pause = float(value)
    except (TypeError, ValueError):
        return DEFAULT_SEGMENT_PAUSE_SECONDS
    return round(clamp_float(pause, MIN_SEGMENT_PAUSE_SECONDS, MAX_SEGMENT_PAUSE_SECONDS), 3)


def make_bandi_voice_segment(
    display_text: str,
    emotion: dict[str, float] | None = None,
    *,
    emotion_strength: float | None = None,
    tts_text: str | None = None,
    pause_after_seconds: float | int | str | None = None,
    aux_limit: int = 3,
    ending_style: str | None = None,
    continuity_mode: str | None = None,
    carry_over: float | int | str | None = None,
) -> BandiVoiceSegment:
    clean_display_text = clean_punctuation(display_text)
    normalized_emotion = normalize_emotion_scores(emotion or {})
    try:
        strength = (
            clamp_float(float(emotion_strength), 0.0, 1.0)
            if emotion_strength is not None
            else _derive_strength(normalized_emotion)
        )
    except (TypeError, ValueError):
        strength = _derive_strength(normalized_emotion)
    normalized_continuity_mode = normalize_continuity_mode(continuity_mode)
    return BandiVoiceSegment(
        display_text=clean_display_text,
        emotion=normalized_emotion,
        emotion_strength=round(strength, 3),
        tts_text=clean_punctuation(tts_text) if tts_text else None,
        pause_after_seconds=normalize_segment_pause(pause_after_seconds),
        aux_limit=max(1, min(int(aux_limit), 5)),
        ending_style=normalize_ending_style(ending_style),
        continuity_mode=normalized_continuity_mode,
        carry_over=normalize_carry_over(carry_over, continuity_mode=normalized_continuity_mode),
    )


def with_segments(
    request: BandiVoiceCommandRequest,
    segments: list[BandiVoiceSegment] | tuple[BandiVoiceSegment, ...],
) -> BandiVoiceCommandRequest:
    clean_segments = tuple(
        segment
        for segment in segments[:MAX_VOICE_SEGMENTS]
        if segment.display_text.strip() or (segment.tts_text or "").strip()
    )
    if not clean_segments:
        return request
    return BandiVoiceCommandRequest(
        display_text=request.display_text,
        emotion=request.emotion,
        emotion_strength=request.emotion_strength,
        tts_text=request.tts_text,
        aux_limit=request.aux_limit,
        ending_style=request.ending_style,
        segments=clean_segments,
    )


def _parse_options(option_text: str) -> tuple[dict[str, float], float | None, str | None, str]:
    emotion: dict[str, float] = {}
    strength: float | None = None
    tts_text: str | None = None
    ending_style = "flat"

    for token in option_text.split():
        if not token:
            continue
        key = ""
        raw_value = ""
        if "=" in token:
            key, raw_value = token.split("=", 1)
        elif ":" in token:
            key, raw_value = token.split(":", 1)

        normalized_key = key.strip().lower()
        if normalized_key in {"emotion", "emotions", "감정", "voice", "mood"}:
            for name, score in _parse_emotion_items(raw_value).items():
                emotion[name] = emotion.get(name, 0.0) + score
            continue
        if normalized_key in {"strength", "emotion_strength", "강도", "표현강도"}:
            try:
                strength = _parse_strength(raw_value)
            except ValueError as exc:
                raise BandiVoicePlanError("감정 강도는 0~1 또는 1~10 숫자로 적어줘.") from exc
            continue
        if normalized_key in {"tts", "tts_text"}:
            tts_text = raw_value.strip() or None
            continue
        if normalized_key in {"ending_style", "intonation", "끝억양", "억양"}:
            ending_style = normalize_ending_style(raw_value)
            continue

        parsed = _parse_emotion_token(token)
        if parsed is not None:
            name, score = parsed
            emotion[name] = emotion.get(name, 0.0) + score

    return emotion, strength, tts_text, ending_style


def parse_bandi_voice_command(raw_text: str) -> BandiVoiceCommandRequest:
    option_text, display_text = _split_option_prefix(raw_text.strip())
    if not display_text:
        raise BandiVoicePlanError("음성으로 만들 말을 같이 적어줘. 예: `/음성생성 감정=기쁨:7,차분:3 | 안녕?`")

    emotion, strength, tts_text, ending_style = _parse_options(option_text)
    if not emotion:
        return BandiVoiceCommandRequest(
            display_text=display_text,
            emotion={},
            emotion_strength=0.0,
            tts_text=tts_text,
            ending_style=ending_style,
        )

    return BandiVoiceCommandRequest(
        display_text=display_text,
        emotion=emotion,
        emotion_strength=strength if strength is not None else _derive_strength(emotion),
        tts_text=tts_text,
        ending_style=ending_style,
    )


def build_runpod_input(
    request: BandiVoiceCommandRequest,
    *,
    request_id: str,
    min_duration_seconds: float,
    retry_attempts: int,
) -> dict[str, Any]:
    if request.has_segments:
        segments = []
        for index, segment in enumerate(request.segments):
            segment_emotion = segment.emotion or request.emotion
            segment_strength = (
                segment.emotion_strength
                if segment.emotion
                else request.emotion_strength
            )
            tts_text = prepare_tts_text(
                segment.display_text,
                segment_emotion,
                segment.tts_text,
                segment.ending_style,
            )
            segments.append(
                {
                    "display_text": segment.display_text,
                    "text": tts_text,
                    "emotion": segment_emotion,
                    "emotion_strength": segment_strength,
                    "ending_style": segment.ending_style,
                    "continuity": {
                        "mode": segment.continuity_mode,
                        "carry_over": segment.carry_over,
                    },
                    "primary_reference": DEFAULT_PRIMARY_REFERENCE,
                    "aux_references": choose_aux_references(segment_emotion, max_refs=segment.aux_limit),
                    "post_filter": choose_post_filter(segment_emotion),
                    "pause_after_seconds": 0.0
                    if index == len(request.segments) - 1
                    else normalize_segment_pause(segment.pause_after_seconds),
                }
            )
        return {
            "request_id": request_id,
            "display_text": request.display_text,
            "text": " ".join(segment["text"] for segment in segments),
            "segments": segments,
            "min_duration_seconds": min_duration_seconds,
            "retry_attempts": retry_attempts,
            "segment_gap_seconds": DEFAULT_SEGMENT_PAUSE_SECONDS,
            "ending_style": request.ending_style,
        }

    if not request.has_emotion_plan:
        return {
            "text": clean_punctuation(request.tts_text or request.display_text),
            "request_id": request_id,
            "min_duration_seconds": min_duration_seconds,
            "retry_attempts": retry_attempts,
        }

    tts_text = prepare_tts_text(request.display_text, request.emotion, request.tts_text, request.ending_style)
    return {
        "request_id": request_id,
        "display_text": request.display_text,
        "text": tts_text,
        "emotion": request.emotion,
        "emotion_strength": request.emotion_strength,
        "ending_style": request.ending_style,
        "primary_reference": DEFAULT_PRIMARY_REFERENCE,
        "aux_references": choose_aux_references(request.emotion, max_refs=request.aux_limit),
        "post_filter": choose_post_filter(request.emotion),
        "min_duration_seconds": min_duration_seconds,
        "retry_attempts": retry_attempts,
        "aux_limit": request.aux_limit,
    }


def format_emotion_summary(request: BandiVoiceCommandRequest) -> str:
    if request.has_segments:
        segment_summaries = []
        for segment in request.segments:
            items = "/".join(
                f"{name}:{score:g}" for name, score in sorted(segment.emotion.items(), key=lambda item: item[1], reverse=True)
            )
            if items:
                segment_summaries.append(items)
        if not segment_summaries:
            return f" 구간={len(request.segments)}개"
        emotion_line = " -> ".join(segment_summaries)
        if len(emotion_line) > 180:
            emotion_line = f"{emotion_line[:177]}..."
        return f" 구간={len(request.segments)}개, 감정선={emotion_line}"
    if not request.has_emotion_plan:
        return ""
    items = ", ".join(
        f"{name}:{score:g}" for name, score in sorted(request.emotion.items(), key=lambda item: item[1], reverse=True)
    )
    return f" 감정={items}, 강도={request.emotion_strength:.2f}"
