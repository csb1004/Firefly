from dataclasses import dataclass
from pathlib import Path
import re

from .config import BANDI_EMOTICON_DIR

EMOTICON_NONE = "none"
EMOTICON_MARKER_RE = re.compile(r"^\s*\[\[EMOTICON:\s*([a-zA-Z0-9_ -]+)\s*\]\]\s*$")


@dataclass(frozen=True)
class BandiEmoticon:
    key: str
    filename: str
    label: str
    use_when: str
    avoid_when: str


@dataclass(frozen=True)
class ParsedEmoticonReply:
    text: str
    emoticon_key: str | None


EMOTICONS: dict[str, BandiEmoticon] = {
    "bandi_gentle": BandiEmoticon(
        key="bandi_gentle",
        filename="반디1.webp",
        label="웃는 반디",
        use_when="밝지만 과하지 않은 인사, 안심시킬 때, 괜찮다고 알려줄 때, 부드러운 긍정",
        avoid_when="애정이 진하게 묻어나는 감사, 돈 문제로 멍해진 상황, 항의나 출격",
    ),
    "bandi_touched": BandiEmoticon(
        key="bandi_touched",
        filename="반디2.webp",
        label="마음 담은 반디",
        use_when="조심스럽고 다정한 고마움, 마음에 든 제안, 작은 감동, 상대의 호의를 소중히 받을 때",
        avoid_when="진한 애정 표현, 가격/지갑 앞의 허탈함, 장난스러운 항의",
    ),
    "bandi_wallet_blank": BandiEmoticon(
        key="bandi_wallet_blank",
        filename="반디3.webp",
        label="지갑 보고 멈춘 반디",
        use_when="돈, 가격, 예산, 지갑, 계산서 이야기에 허탈하거나 멍해질 때, 남의 돈을 쓰기 어색할 때",
        avoid_when="진심 어린 사과, 단순한 피곤함, 귀엽게 항의하는 상황",
    ),
    "sam_ready": BandiEmoticon(
        key="sam_ready",
        filename="반디4.webp",
        label="샘 출격",
        use_when="단호한 결심, 보호하려는 태도, 실행/출격/전투적 에너지, 위기 대응",
        avoid_when="일상 대화, 다정한 애정 표현, 슬픈 장면",
    ),
    "ghost_deadpan": BandiEmoticon(
        key="ghost_deadpan",
        filename="울보유령1.webp",
        label="정색한 유령",
        use_when="말문이 막힌 정색, 어이없는 오해를 차분히 부정할 때, 힘 빠진 반박",
        avoid_when="돈 문제로 멍해진 상황, 부끄러워서 항의하는 상황, 진지한 슬픔",
    ),
    "ghost_protest": BandiEmoticon(
        key="ghost_protest",
        filename="울보유령2.webp",
        label="귀엽게 항의하는 유령",
        use_when="부끄러움 섞인 항의, 놀림받았을 때의 볼멘 반응, '그건 아니야'를 귀엽게 말할 때",
        avoid_when="실제 공포, 큰 실수, 단순한 피로",
    ),
    "pom_awkward": BandiEmoticon(
        key="pom_awkward",
        filename="폼폼1.webp",
        label="난감한 폼폼",
        use_when="이미지 전송 실패처럼 일이 꼬였을 때, 같은 행동을 반복해버린 민망함, 작게 미안하고 난감한 상황",
        avoid_when="상대의 슬픔에 대한 위로, 깊은 공감, 애정 표현",
    ),
    "pom_heart": BandiEmoticon(
        key="pom_heart",
        filename="폼폼2.webp",
        label="하트 폼폼",
        use_when="애정, 친밀한 고마움, 아주 따뜻한 칭찬, 마음을 전하고 싶을 때",
        avoid_when="평범한 인사, 단순 승인, 사과",
    ),
    "pom_song": BandiEmoticon(
        key="pom_song",
        filename="폼폼3.webp",
        label="노래하는 폼폼",
        use_when="확실히 신났을 때, 즐거운 장난, 가벼운 축하, 노래/광고송/들뜬 분위기",
        avoid_when="진지한 고민 상담, 슬픔, 사과",
    ),
    "pom_approve": BandiEmoticon(
        key="pom_approve",
        filename="폼폼4.webp",
        label="칭찬 폼폼",
        use_when="승인, 성공, 잘했다는 칭찬, 작업 완료 확인, 자신감을 북돋울 때",
        avoid_when="애정 고백, 슬픔, 당황",
    ),
    "pom_shy": BandiEmoticon(
        key="pom_shy",
        filename="폼폼5.webp",
        label="부끄러운 폼폼",
        use_when="칭찬을 받아 민망함, 장난스러운 수줍음, 살짝 들킨 마음, 귀여운 난처함",
        avoid_when="큰 실수에 대한 당황, 사과, 진지한 애정 표현",
    ),
    "pom_wave": BandiEmoticon(
        key="pom_wave",
        filename="폼폼6.webp",
        label="손 흔드는 폼폼",
        use_when="밝은 인사, 작별, 시작을 응원하는 말, 가볍게 앞으로 나아가자는 분위기",
        avoid_when="차분한 맞장구, 슬픔, 단호한 실행",
    ),
}

EMOTICON_ALIASES = {
    "bandi_sorry": "bandi_wallet_blank",
    "ghost_tired": "ghost_deadpan",
    "ghost_flustered": "ghost_protest",
    "pom_sad": "pom_awkward",
}


def _normalize_emoticon_key(key: str) -> str:
    return key.strip().lower().replace("-", "_").replace(" ", "_")


def _resolve_emoticon_key(key: str) -> str:
    normalized = _normalize_emoticon_key(key)
    return EMOTICON_ALIASES.get(normalized, normalized)


def parse_reply_emoticon(reply: str) -> ParsedEmoticonReply:
    lines = reply.strip().splitlines()
    marker_index = None
    marker_key = None

    for index in range(len(lines) - 1, -1, -1):
        line = lines[index].strip()
        if not line:
            continue
        marker_match = EMOTICON_MARKER_RE.match(line)
        if marker_match is None:
            break
        marker_index = index
        marker_key = _resolve_emoticon_key(marker_match.group(1))
        break

    if marker_index is None:
        return ParsedEmoticonReply(text=reply.strip(), emoticon_key=None)

    remaining_lines = lines[:marker_index] + lines[marker_index + 1:]
    text = "\n".join(remaining_lines).strip()
    if marker_key == EMOTICON_NONE or marker_key not in EMOTICONS:
        return ParsedEmoticonReply(text=text, emoticon_key=None)
    return ParsedEmoticonReply(text=text, emoticon_key=marker_key)


def get_emoticon_path(key: str | None) -> Path | None:
    if key is None:
        return None
    emoticon = EMOTICONS.get(_resolve_emoticon_key(key))
    if emoticon is None:
        return None
    path = BANDI_EMOTICON_DIR / emoticon.filename
    if not path.exists() or not path.is_file():
        return None
    return path


def build_emoticon_prompt() -> str:
    guide_lines = [
        "[반디 이모티콘 선택 규칙]",
        f"- 자연스러운 대화 답변의 마지막 줄에 반드시 `[[EMOTICON: {EMOTICON_NONE}]]` 또는 `[[EMOTICON: 키]]`를 적는다.",
        "- 마지막 줄은 디스코드 전송용 지시라서 본문에 설명하지 않는다.",
        "- 이모티콘은 답변당 최대 1개만 고른다. 감정 신호가 뚜렷하지 않거나 진지한 정보 전달이면 `none`을 고른다.",
        "- 봇 명령어 한 줄만 출력해야 하는 경우에는 이모티콘 줄을 붙이지 않는다.",
        "- 같은 상황에 여러 후보가 있으면 아래의 `use_when`이 가장 정확한 하나만 고른다.",
        "",
        "[사용 가능한 이모티콘 키]",
    ]
    for emoticon in EMOTICONS.values():
        guide_lines.append(
            f"- `{emoticon.key}`: {emoticon.label}. 사용: {emoticon.use_when}. 피함: {emoticon.avoid_when}."
        )
    guide_lines.append(f"- `{EMOTICON_NONE}`: 위 상황에 정확히 맞지 않거나, 이모티콘이 대화의 톤을 방해할 때.")
    return "\n".join(guide_lines)
