import asyncio
import re

from openai import APIError, OpenAI, RateLimitError

from .affection import adjust_affection
from .brain import format_brain_notes
from .config import (
    BOT_DISPLAY_NAME,
    COMMAND_GUIDE_FILE,
    DEFAULT_AFFECTION,
    DEFAULT_MODEL,
    NEWS_PROMPT_FILE,
    OPENAI_API_KEY,
    SPECIAL_USER_ID,
    SPECIAL_COMMAND_GUIDE_FILE,
    STATE_UPDATER_MODEL,
    STATE_UPDATER_PROMPT_FILE,
    SUMMARY_DEFAULT_LIMIT,
    TOOL_PLANNER_MODEL,
    TOOL_PLANNER_PROMPT_FILE,
    WEB_SEARCH_MODEL,
)
from .content import LONG_SAM_LINE
from .prompts import (
    build_group_context_prompt,
    build_model_history,
    build_room_model_history,
    build_system_prompt,
)
from .relationship_events import RELATIONSHIP_EVENTS_KEY, build_relationship_event_context
from .reasoning import normalize_room_reasoning_effort
from .storage import (
    add_history,
    add_room_history,
    get_room_data,
    get_user_data,
    update_room_data,
    update_user_data,
)
from .state_updates import filter_hidden_state_update_commands
from .text_utils import get_current_time_text, is_command_text, load_text_file
from .tool_planner import PLAN_CHAT, ToolPlan, parse_tool_plan

client_openai = OpenAI(api_key=OPENAI_API_KEY)
STATE_UPDATE_CONTEXT_HISTORY_LIMIT = 6
STATE_UPDATE_CONFIDENCE_THRESHOLD = 0.1


def _is_auto_command_reply(reply: str) -> bool:
    lines = [line.strip() for line in reply.strip().splitlines() if line.strip()]
    return len(lines) == 1 and is_command_text(lines[0]) and lines[0] != "/"


def _format_allowed_command_prefixes(command_prefixes: tuple[str, ...]) -> str:
    return ", ".join(command_prefixes)


def _format_state_history(entries: list[dict], *, limit: int = STATE_UPDATE_CONTEXT_HISTORY_LIMIT) -> str:
    lines = []
    for entry in entries[-limit:]:
        role = str(entry.get("role") or "unknown")
        speaker = str(entry.get("speaker") or role)
        content = str(entry.get("content") or "").strip()
        if content:
            lines.append(f"- {speaker}: {content[:500]}")
    return "\n".join(lines) if lines else "- 없음"


async def generate_silent_auto_command(
    user_message: str,
    user_id: int,
    display_name: str,
    room_key: str,
    *,
    allowed_command_prefixes: tuple[str, ...],
) -> str | None:
    user_data = get_user_data(user_id, display_name)
    room_data = get_room_data(room_key)
    reasoning_effort = normalize_room_reasoning_effort(room_data)
    system_prompt = build_system_prompt(
        user_id,
        user_data,
        include_command_guides=True,
    )
    system_prompt = f"""
{system_prompt}

[조용한 단체 대화 업데이트 점검]
- 이 호출은 공개 답장을 만들지 않는다.
- 꼭 필요한 자동 명령이 있을 때만 명령어 한 줄을 출력한다.
- 필요 없으면 설명 없이 `없음`만 출력한다.
- 일반 답변, 인사, 사족은 출력하지 않는다.
- 허용 명령: {_format_allowed_command_prefixes(allowed_command_prefixes)}
""".strip()

    if room_data.get("group_mode", False):
        group_context = build_group_context_prompt(
            display_name=display_name,
            user_id=user_id,
            user_data=user_data,
            room_data=room_data,
        )
        system_prompt = f"{system_prompt}\n\n{group_context}"

    input_messages = [{"role": "system", "content": system_prompt}]
    if room_data.get("group_mode", False):
        input_messages.extend(build_room_model_history(room_data.get("history", [])))
        input_messages.append({
            "role": "user",
            "content": (
                f"[이름={display_name}, "
                f"호칭={user_data.get('nickname')}, "
                f"호감도={user_data.get('affection')}] {user_message}"
            ),
        })
    else:
        input_messages.extend(build_model_history(user_data.get("history", [])))
        input_messages.append({"role": "user", "content": user_message})

    try:
        response = await asyncio.to_thread(
            client_openai.responses.create,
            model=DEFAULT_MODEL,
            input=input_messages,
            reasoning={"effort": reasoning_effort},
        )
    except Exception as exc:
        print("Silent auto command generation error:", exc)
        return None

    reply = response.output_text.strip()
    if not _is_auto_command_reply(reply):
        return None
    if not any(
        reply == prefix or reply.startswith(f"{prefix} ")
        for prefix in allowed_command_prefixes
    ):
        return None
    return reply[:1900]


def _build_tool_planner_system_prompt(*, special_user: bool) -> str:
    guides = [load_text_file(COMMAND_GUIDE_FILE)]
    if special_user:
        guides.append(load_text_file(SPECIAL_COMMAND_GUIDE_FILE))
    command_guides = "\n\n".join(guides)
    return f"""
{load_text_file(TOOL_PLANNER_PROMPT_FILE)}

[사용 가능한 명령어 규칙]
{command_guides}
""".strip()


async def plan_tool_use(
    user_message: str,
    user_id: int,
    display_name: str,
    room_key: str,
    *,
    special_user: bool,
    attachment_context: str | None = None,
) -> ToolPlan | None:
    if user_message.strip().startswith("/"):
        return None

    room_data = get_room_data(room_key)
    user_data = get_user_data(user_id, display_name)
    system_prompt = _build_tool_planner_system_prompt(special_user=special_user)

    context_lines = [
        f"- 사용자 디스코드 ID: {user_id}",
        f"- 사용자 표시 이름: {display_name}",
        f"- 관리 권한 사용자 여부: {'yes' if special_user else 'no'}",
        f"- 단체 모드: {'on' if room_data.get('group_mode') else 'off'}",
        f"- 인터넷 모드: {'on' if room_data.get('internet_mode') else 'off'}",
        f"- 저장된 호칭: {user_data.get('nickname', '없음')}",
    ]
    if attachment_context:
        context_lines.append("- 첨부 파일 내용이 함께 있음: yes")

    planner_user_message = f"""
[현재 컨텍스트]
{chr(10).join(context_lines)}

[사용자 입력]
{user_message}
""".strip()

    try:
        response = await asyncio.to_thread(
            client_openai.responses.create,
            model=TOOL_PLANNER_MODEL,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": planner_user_message},
            ],
        )
    except Exception as exc:
        print("Tool planner error:", exc)
        return None

    plan = parse_tool_plan(response.output_text.strip())
    if plan is None:
        return None
    if plan.confidence < 0.2:
        return None
    if plan.mode == PLAN_CHAT:
        return plan
    return plan


async def plan_state_updates(
    user_message: str,
    user_id: int,
    display_name: str,
    room_key: str,
    *,
    attachment_context: str | None = None,
) -> tuple[str, ...]:
    if user_message.strip().startswith("/"):
        return ()

    room_data = get_room_data(room_key)
    user_data = get_user_data(user_id, display_name)
    brain_context = format_brain_notes(dict(user_data))
    attachment_line = ""
    if attachment_context:
        attachment_line = f"\n[첨부 맥락]\n{attachment_context[:1800]}"

    planner_user_message = f"""
[현재 사용자]
- 디스코드 ID: {user_id}
- 표시 이름: {display_name}
- 저장된 호칭: {user_data.get('nickname', '없음')}
- 현재 호감도: {user_data.get('affection', DEFAULT_AFFECTION)}
- 특별 사용자 여부: {'yes' if user_id == SPECIAL_USER_ID else 'no'}

[반디가 이미 가진 키워드 점수 딕셔너리]
{brain_context}

[키워드 평가 지침]
- 이번 입력을 평가하기 전에 위 키워드 목록을 먼저 본다.
- 비슷한 의미는 새 키워드로 만들지 말고 가능한 한 기존 키워드 이름으로 병합한다.
- 새로 저장할 때는 `/뇌추가 {user_id} 키워드: 점수` 형식을 쓰고, 점수는 이번 입력에서 관찰된 강도 1~5만 쓴다.
- 여러 신호가 있으면 한 명령 안에서 `키워드: 점수 | 키워드: 점수`처럼 묶는다.

[최근 개인 대화]
{_format_state_history(user_data.get('history', []))}

[최근 방 대화]
{_format_state_history(room_data.get('history', []))}
{attachment_line}

[이번 사용자 입력]
{user_message}
""".strip()

    try:
        response = await asyncio.to_thread(
            client_openai.responses.create,
            model=STATE_UPDATER_MODEL,
            input=[
                {"role": "system", "content": load_text_file(STATE_UPDATER_PROMPT_FILE)},
                {"role": "user", "content": planner_user_message},
            ],
        )
    except Exception as exc:
        print("State updater planner error:", exc)
        return ()

    plan = parse_tool_plan(response.output_text.strip())
    if plan is None or plan.mode != "command" or plan.confidence < STATE_UPDATE_CONFIDENCE_THRESHOLD:
        return ()

    return filter_hidden_state_update_commands(plan.commands, user_id=user_id)


NEWS_FIELD_LABELS = ("무슨 일", "왜 중요해", "확인 링크")
NEWS_OMITTED_FIELD_LABELS = ("왜 중요해",)
NEWS_TREND_FALLBACK_DAYS = 7
NEWS_SELECTION_PRIORITIES = (
    "1순위: 주요 언론, 공식 발표, 정부/표준기구/학회/연구기관 자료에서 확인되는 큰 사건을 먼저 고른다.",
    "2순위: 대규모 모델/제품 출시, 인수합병, 규제/정책 변화, 반도체/클라우드/보안 사고, 널리 쓰이는 런타임/프레임워크의 주요 버전 발표를 고른다.",
    "3순위: 대형 뉴스가 3개 미만일 때만 논문, 보안 권고, 주요 패키지 릴리스, 기술 동향 글로 보강한다.",
)
NEWS_EXCLUDED_SIGNALS = (
    "GitHub 저장소의 개별 PR/이슈, 트렌딩 저장소, 작은 changelog 한 줄 같은 단순 업데이트는 전하지 않는다.",
    "GitHub Copilot, IDE, 개발자 도구의 사소한 기능 추가나 UI 변경은 여러 매체가 의미 있게 다룬 큰 변화가 아니면 전하지 않는다.",
    "한 회사의 작은 릴리스 노트는 업계 영향이 큰 뉴스, 공식 발표, 보안/정책/연구 성과가 아닐 때 제외한다.",
)
NEWS_SOURCE_CATEGORIES = (
    "주요 뉴스와 공식 발표: 주요 기술 매체, 회사/연구소/정부/표준기구의 보도자료와 공식 블로그",
    "한국 AI/반도체/산업 뉴스: 서울경제, 전자신문, 디지털데일리, ZDNet Korea, 더밀크, AI타임스, 디일렉, IT조선 같은 국내 기사와 산업 분석",
    "공식 릴리스 노트: AI 연구소, 클라우드/반도체 회사, 언어/프레임워크/개발자 도구 프로젝트의 주요 버전 발표와 changelog",
    "연구/논문: arXiv, OpenReview, NeurIPS, ICML, ICLR, CVPR, ACL, EMNLP, Papers with Code, Hugging Face Papers",
    "보안/인프라: CVE/NVD, GitHub Security Advisories, CNCF/Kubernetes, 주요 클라우드 보안 공지와 장애/변경 공지",
    "기술 뉴스와 동향: The Register, InfoQ, IEEE Spectrum, ACM/IEEE, Hacker News, 주요 기술 뉴스레터와 커뮤니티 요약",
    "메이저 오픈소스 생태계: Python, JavaScript/TypeScript, Rust, Go, Java, .NET, Kubernetes, Docker, GitHub Actions 같은 널리 쓰이는 프로젝트의 주요 릴리스와 advisories",
    "국내 영상/커뮤니티 발견 신호: 안될공학 - IT 테크 신기술 같은 빠른 기술 해설 채널은 후보를 찾는 데 참고하되, 포함 전에는 원 발표/기사/논문/공식 자료로 다시 확인",
)
NEWS_TOPIC_SOURCE_HINTS = (
    (
        ("인공지능", "ai", "llm", "머신러닝", "딥러닝", "강화학습"),
        (
            "AI 주제는 모델/제품 발표뿐 아니라 새 논문, benchmark, dataset, evaluation, safety, agent/tooling 동향까지 확인한다.",
            "대형 발표가 없으면 arXiv cs.AI/cs.LG/cs.CL/cs.CV, OpenReview, 컨퍼런스 accepted paper/workshop 페이지, Hugging Face Papers를 우선 보강한다.",
            "한국어 기사도 확인해서 서울경제처럼 AI 반도체, HBM, 클라우드, 로봇, 국내 기업/정책과 연결된 산업 뉴스를 놓치지 않는다.",
            "유튜브 안될공학처럼 빠른 해설 채널은 신호로 참고하되, 영상 주장만으로 단정하지 말고 원문 링크를 찾아 검증한다.",
        ),
    ),
    (
        ("프로그래밍", "개발", "software", "programming", "developer", "코딩"),
        (
            "프로그래밍 주제는 언어/런타임/프레임워크 릴리스, 개발자 도구, 패키지 생태계, 보안 권고, 빌드/배포 인프라 변화를 확인한다.",
            "대형 뉴스가 없으면 Python, JavaScript/TypeScript, Rust, Go, Java, .NET, Kubernetes, Docker, GitHub Actions 관련 release note와 advisories를 보강한다.",
        ),
    ),
)


def _normalize_news_digest_format(text: str) -> str:
    field_pattern = "|".join(re.escape(label) for label in NEWS_FIELD_LABELS)

    def replace_field_number(match: re.Match) -> str:
        indent, bold_open, label, bold_close = match.groups()
        bold_open = bold_open or ""
        bold_close = bold_close or ""
        return f"{indent}- {bold_open}{label}{bold_close}:"

    text = re.sub(
        rf"(?m)^(\s*)\d+\.\s*(\*\*)?({field_pattern})(\*\*)?\s*:",
        replace_field_number,
        text.strip(),
    )

    item_index = 0

    def replace_ordered_item(match: re.Match) -> str:
        nonlocal item_index
        item_index += 1
        title = match.group(1).strip()
        return f"[{item_index}] {title}"

    text = re.sub(r"(?m)^\s*\d+\.\s+(.+)$", replace_ordered_item, text)
    omitted_pattern = "|".join(re.escape(label) for label in NEWS_OMITTED_FIELD_LABELS)
    if omitted_pattern:
        text = re.sub(
            rf"(?m)^\s*-\s*(?:\*\*)?(?:{omitted_pattern})(?:\*\*)?\s*:.*(?:\n(?!\s*(?:-|\[\d+\])\s).*)*",
            "",
            text,
        )

    text = re.sub(r"\n{3,}", "\n\n", text)
    return re.sub(r"\n+(?=\[\d+\]\s+)", "\n\n", text).strip()


def _news_topic_source_hints(topics: list[str]) -> list[str]:
    topic_text = " ".join(topics).casefold()
    hints = []
    seen = set()

    for keywords, topic_hints in NEWS_TOPIC_SOURCE_HINTS:
        if not any(keyword.casefold() in topic_text for keyword in keywords):
            continue

        for hint in topic_hints:
            if hint in seen:
                continue
            hints.append(hint)
            seen.add(hint)

    return hints


def _format_news_source_guidance(topics: list[str], *, broaden_search: bool) -> str:
    lines = [
        "[선정 우선순위]",
        *NEWS_SELECTION_PRIORITIES,
        "",
        "[제외 신호]",
        *NEWS_EXCLUDED_SIGNALS,
        "",
        "[검색 범위]",
        "먼저 주요 뉴스와 공식 발표에서 큰 사건을 찾고, 부족할 때도 GitHub 단순 업데이트는 제외한 채 패키지 생태계의 주요 릴리스와 보안 권고만 확인해.",
    ]
    lines.extend(f"- {category}" for category in NEWS_SOURCE_CATEGORIES)

    topic_hints = _news_topic_source_hints(topics)
    if topic_hints:
        lines.append("")
        lines.append("[주제별 보강]")
        lines.extend(f"- {hint}" for hint in topic_hints)

    if broaden_search:
        lines.append("")
        lines.append("[보강 검색 모드]")
        lines.append("- 첫 검색 결과가 없거나 이미 전달한 항목뿐이었다. 대형 뉴스보다 사실 확인 가능한 새 자료를 우선해서 다시 찾아.")
        lines.append(
            f"- 조회 기간 안의 항목을 우선하되, 그래도 3개 미만이면 최근 {NEWS_TREND_FALLBACK_DAYS}일 이내 공개된 "
            "논문, 릴리스 노트, 보안 권고, 컨퍼런스/워크숍 자료, 기술 동향 글을 보강 동향으로 포함할 수 있어."
        )
        lines.append("- 보강 동향은 공개일이나 대상 기간을 본문에 명시하고, 오래된 소식을 오늘 일어난 일처럼 쓰지 마.")

    return "\n".join(lines)


def build_daily_news_digest_prompt(
    topics: list[str],
    window_start_text: str,
    window_end_text: str,
    previously_sent_items: list[str] | None = None,
    *,
    broaden_search: bool = False,
) -> tuple[str, str]:
    topic_text = ", ".join(topics)
    previously_sent_items = previously_sent_items or []
    previously_sent_text = (
        "\n".join(f"- {item}" for item in previously_sent_items)
        if previously_sent_items
        else "없음"
    )
    system_prompt = load_text_file(NEWS_PROMPT_FILE)
    source_guidance = _format_news_source_guidance(topics, broaden_search=broaden_search)
    user_prompt = f"""
[조회 기간]
{window_start_text}부터 {window_end_text}까지, 한국 시간 기준.

[관심 주제]
{topic_text}

[이미 전달한 소식]
{previously_sent_text}

{source_guidance}

[요청]
위 기간에 공개되거나 보도된 최신 소식 중, 관심 주제와 관련되고 사실 확인 가능한 소식만 웹 검색으로 확인해서 정리해줘.
각 항목에는 반드시 확인 가능한 링크를 붙여줘.
확실한 링크와 날짜 근거가 부족하면 항목에서 제외해줘.
이미 전달한 소식과 같은 사건, 같은 링크, 같은 발표는 제외해줘.
중요한 이유나 해석은 쓰지 말고, 확인된 사실만 간결하게 써줘.
""".strip()
    return system_prompt, user_prompt


async def generate_reply(
    user_message: str,
    user_id: int,
    display_name: str,
    room_key: str,
    *,
    extra_context: str | None = None,
    attachment_context: str | None = None,
    force_web_search: bool = False,
    allow_command_output: bool = True,
    persist_command_reply: bool = True,
    apply_affection_adjustment: bool = True,
) -> str:
    if user_message.strip() == "그 긴거 해줘":
        return LONG_SAM_LINE

    user_data = get_user_data(user_id, display_name)
    room_data = get_room_data(room_key)

    group_mode = room_data.get("group_mode", False)
    internet_mode = force_web_search or room_data.get("internet_mode", False)
    reasoning_effort = normalize_room_reasoning_effort(room_data)

    before_affection = int(user_data.get("affection", DEFAULT_AFFECTION))
    if apply_affection_adjustment:
        user_data = adjust_affection(user_id, user_data, user_message)
    after_affection = int(user_data.get("affection", DEFAULT_AFFECTION))
    applied_delta = after_affection - before_affection

    relationship_context = build_relationship_event_context(user_data, user_message)
    relationship_events = dict(user_data.get(RELATIONSHIP_EVENTS_KEY, {}))
    system_prompt = build_system_prompt(
        user_id,
        user_data,
        include_command_guides=allow_command_output,
    )
    if relationship_context:
        system_prompt = f"{system_prompt}\n\n{relationship_context}"

    if group_mode:
        group_context = build_group_context_prompt(
            display_name=display_name,
            user_id=user_id,
            user_data=user_data,
            room_data=room_data,
        )
        system_prompt = f"{system_prompt}\n\n{group_context}"

    model_user_message = user_message
    if attachment_context:
        model_user_message = f"{model_user_message}\n\n{attachment_context}".strip()
    if extra_context:
        response_instruction = "명령어 결과를 사실로 사용해서 사용자 요청에 자연스럽게 답해."
        if allow_command_output:
            response_instruction = (
                "명령어 결과를 사실로 사용해서 사용자 요청을 처리해. "
                "이미 받은 결과만으로 답할 수 있으면 명령어를 더 출력하지 말고 자연스럽게 답해. "
                "아직 추가 봇 명령어 실행이 꼭 필요하면 `/실행`으로 감싸지 말고 실제 다음 명령어 한 줄만 출력해. "
                "더 실행할 명령어가 없으면 자연스럽게 답해."
            )
        model_user_message = f"""
[사용자 요청]
{user_message}

[먼저 실행한 명령어 결과]
{extra_context}

[응답 지침]
{response_instruction}
""".strip()

    input_messages = [{"role": "system", "content": system_prompt}]

    if group_mode:
        input_messages.extend(build_room_model_history(room_data.get("history", [])))
        input_messages.append({
            "role": "user",
            "content": (
                f"[이름={display_name}, "
                f"호칭={user_data.get('nickname')}, "
                f"호감도={user_data.get('affection')}] {model_user_message}"
            ),
        })
    else:
        input_messages.extend(build_model_history(user_data.get("history", [])))
        input_messages.append({
            "role": "user",
            "content": model_user_message,
        })

    try:
        request_kwargs = {
            "model": WEB_SEARCH_MODEL if internet_mode else DEFAULT_MODEL,
            "input": input_messages,
            "reasoning": {"effort": reasoning_effort},
        }

        if internet_mode:
            request_kwargs["tools"] = [{"type": "web_search"}]

        response = await asyncio.to_thread(
            client_openai.responses.create,
            **request_kwargs,
        )
        reply = response.output_text.strip()

        if not persist_command_reply and _is_auto_command_reply(reply):
            return reply

        latest_user_data = get_user_data(user_id, display_name)
        if relationship_events:
            latest_user_data[RELATIONSHIP_EVENTS_KEY] = relationship_events
        if user_id == SPECIAL_USER_ID:
            latest_user_data["affection"] = 1004
        else:
            latest_affection = int(latest_user_data.get("affection", DEFAULT_AFFECTION))
            latest_user_data["affection"] = max(1, min(100, latest_affection + applied_delta))

        if not group_mode:
            latest_user_data = add_history(latest_user_data, "user", user_message)
            latest_user_data = add_history(
                latest_user_data,
                "assistant",
                reply,
                affection_before=before_affection,
                affection_delta=applied_delta,
                affection_after=latest_user_data.get("affection"),
            )

        latest_user_data["last_seen"] = get_current_time_text()
        update_user_data(user_id, latest_user_data)

        latest_room_data = get_room_data(room_key)
        room_data = add_room_history(
            latest_room_data,
            speaker_name=display_name,
            role="user",
            content=user_message,
            user_id=user_id,
            nickname=latest_user_data.get("nickname"),
            affection=latest_user_data.get("affection"),
        )
        room_data = add_room_history(
            room_data,
            speaker_name=BOT_DISPLAY_NAME,
            role="assistant",
            content=reply,
        )
        update_room_data(room_key, room_data)

        return reply

    except RateLimitError as e:
        error_text = str(e)
        if "insufficient_quota" in error_text:
            return "…지금은 OpenAI API 사용 한도가 다 된 것 같아."
        return "…지금은 요청이 조금 몰린 것 같아. 잠깐 뒤에 다시 불러줘."
    except APIError as e:
        print("APIError:", e)
        return "…지금은 연결이 조금 불안정해."
    except Exception as e:
        print("오류:", e)
        return "…미안. 지금은 조금 불안정해."


def _format_summary_entries(entries: list[dict], limit: int) -> list[str]:
    filtered = []
    for item in entries:
        content = item.get("content", "")
        if not isinstance(content, str):
            continue

        content = content.strip()
        if not content or is_command_text(content):
            continue

        speaker = item.get("speaker")
        role = item.get("role", "unknown")

        if speaker:
            label = speaker
        elif role == "assistant":
            label = BOT_DISPLAY_NAME
        else:
            label = "사용자"

        filtered.append(f"{label}: {content}")

    return filtered[-limit:]


async def summarize_conversation(
    entries: list[dict],
    scope_name: str,
    limit: int = SUMMARY_DEFAULT_LIMIT,
) -> tuple[str, int]:
    lines = _format_summary_entries(entries, limit)
    if not lines:
        return "요약할 대화가 아직 없어.", 0

    system_prompt = (
        "너는 디스코드 대화를 짧고 정확하게 정리하는 도우미야. "
        "명령어가 아닌 실제 대화 내용만 바탕으로 한국어로 요약해. "
        "중요한 결정, 감정 흐름, 할 일, 미해결 질문이 있으면 구분해서 적어. "
        "없는 항목은 억지로 만들지 마."
    )
    user_prompt = f"""
[요약 대상]
{scope_name}

[최근 대화]
{chr(10).join(lines)}

[출력 형식]
- 핵심 요약: 2~5문장
- 결정/합의: 있으면 짧게
- 남은 할 일/질문: 있으면 짧게
""".strip()

    try:
        response = await asyncio.to_thread(
            client_openai.responses.create,
            model=DEFAULT_MODEL,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.output_text.strip(), len(lines)
    except RateLimitError as e:
        error_text = str(e)
        if "insufficient_quota" in error_text:
            return "…지금은 OpenAI API 사용 한도가 다 된 것 같아서 요약을 만들 수 없어.", len(lines)
        return "…요약 요청이 조금 몰린 것 같아. 잠깐 뒤에 다시 해줘.", len(lines)
    except APIError as e:
        print("Summary APIError:", e)
        return "…요약 중 연결이 조금 불안정했어.", len(lines)
    except Exception as e:
        print("Summary error:", e)
        return "…미안. 지금은 요약을 만들 수 없어.", len(lines)


async def generate_daily_news_digest(
    topics: list[str],
    window_start_text: str,
    window_end_text: str,
    previously_sent_items: list[str] | None = None,
    *,
    broaden_search: bool = False,
) -> str | None:
    system_prompt, user_prompt = build_daily_news_digest_prompt(
        topics=topics,
        window_start_text=window_start_text,
        window_end_text=window_end_text,
        previously_sent_items=previously_sent_items,
        broaden_search=broaden_search,
    )

    try:
        response = await asyncio.to_thread(
            client_openai.responses.create,
            model=WEB_SEARCH_MODEL,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            tools=[{"type": "web_search"}],
        )
        return _normalize_news_digest_format(response.output_text)
    except RateLimitError as e:
        error_text = str(e)
        if "insufficient_quota" in error_text:
            print("Daily news quota exhausted.")
        else:
            print("Daily news rate limited:", e)
        return None
    except APIError as e:
        print("Daily news APIError:", e)
        return None
    except Exception as e:
        print("Daily news error:", e)
        return None
