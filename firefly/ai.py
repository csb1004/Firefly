import asyncio

from openai import APIError, OpenAI, RateLimitError

from .affection import adjust_affection
from .config import (
    BOT_DISPLAY_NAME,
    DEFAULT_AFFECTION,
    DEFAULT_MODEL,
    NEWS_PROMPT_FILE,
    OPENAI_API_KEY,
    SPECIAL_USER_ID,
    SUMMARY_DEFAULT_LIMIT,
    WEB_SEARCH_MODEL,
)
from .content import LONG_SAM_LINE
from .prompts import (
    build_group_context_prompt,
    build_model_history,
    build_room_model_history,
    build_system_prompt,
)
from .storage import (
    add_history,
    add_room_history,
    get_room_data,
    get_user_data,
    update_room_data,
    update_user_data,
)
from .text_utils import get_current_time_text, is_command_text, load_text_file

client_openai = OpenAI(api_key=OPENAI_API_KEY)


async def generate_reply(
    user_message: str,
    user_id: int,
    display_name: str,
    room_key: str,
) -> str:
    if user_message.strip() == "그 긴거 해줘":
        return LONG_SAM_LINE

    user_data = get_user_data(user_id, display_name)
    room_data = get_room_data(room_key)

    group_mode = room_data.get("group_mode", False)
    internet_mode = room_data.get("internet_mode", False)

    before_affection = int(user_data.get("affection", DEFAULT_AFFECTION))
    user_data = adjust_affection(user_id, user_data, user_message)
    after_affection = int(user_data.get("affection", DEFAULT_AFFECTION))
    applied_delta = after_affection - before_affection

    system_prompt = build_system_prompt(user_id, user_data)

    if group_mode:
        group_context = build_group_context_prompt(
            display_name=display_name,
            user_id=user_id,
            user_data=user_data,
            room_data=room_data,
        )
        system_prompt = f"{system_prompt}\n\n{group_context}"

    input_messages = [{"role": "system", "content": system_prompt}]

    if group_mode:
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
        input_messages.append({
            "role": "user",
            "content": user_message,
        })

    try:
        request_kwargs = {
            "model": WEB_SEARCH_MODEL if internet_mode else DEFAULT_MODEL,
            "input": input_messages,
        }

        if internet_mode:
            request_kwargs["tools"] = [{"type": "web_search"}]

        response = await asyncio.to_thread(
            client_openai.responses.create,
            **request_kwargs,
        )
        reply = response.output_text.strip()

        latest_user_data = get_user_data(user_id, display_name)
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
) -> str | None:
    topic_text = ", ".join(topics)
    system_prompt = load_text_file(NEWS_PROMPT_FILE)
    user_prompt = f"""
[조회 기간]
{window_start_text}부터 {window_end_text}까지, 한국 시간 기준.

[관심 주제]
{topic_text}

[요청]
위 기간에 공개되거나 보도된 최신 소식 중, 관심 주제와 관련된 중요한 소식만 웹 검색으로 확인해서 정리해줘.
각 항목에는 반드시 확인 가능한 링크를 붙여줘.
확실한 링크와 날짜 근거가 부족하면 항목에서 제외해줘.
""".strip()

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
        return response.output_text.strip()
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
