import asyncio
import re
from datetime import datetime, timedelta, timezone

import discord

from .ai import generate_daily_news_digest
from .config import (
    DAILY_NEWS_KEY,
    NEWS_DEFAULT_HOUR,
    NEWS_DEFAULT_MINUTE,
    NEWS_DEFAULT_TOPICS,
    SPECIAL_USER_ID,
)
from .storage import update_memory

KST = timezone(timedelta(hours=9))
NEWS_COMMAND_PREFIX = "/최신 소식"
NEWS_COMMAND_ALIASES = ("/최신 소식", "/최신소식")
TOPIC_COMMAND_PREFIX = "/주제"
NEWS_MESSAGE_LIMIT = 1900

_news_task: asyncio.Task | None = None


class NewsCommandError(ValueError):
    pass


def _now_kst() -> datetime:
    return datetime.now(KST)


def _format_kst(dt: datetime) -> str:
    return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M")


def _format_delivery_time(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def _default_news_settings() -> dict:
    return {
        "hour": NEWS_DEFAULT_HOUR,
        "minute": NEWS_DEFAULT_MINUTE,
        "topics": list(NEWS_DEFAULT_TOPICS),
        "subscribers": {},
        "last_delivered_window_end": None,
    }


def _normalize_news_settings(settings: dict | None) -> dict:
    if not isinstance(settings, dict):
        settings = {}

    try:
        hour = int(settings.get("hour", NEWS_DEFAULT_HOUR))
        minute = int(settings.get("minute", NEWS_DEFAULT_MINUTE))
    except (TypeError, ValueError):
        hour = NEWS_DEFAULT_HOUR
        minute = NEWS_DEFAULT_MINUTE

    if not 0 <= hour <= 23:
        hour = NEWS_DEFAULT_HOUR
    if not 0 <= minute <= 59:
        minute = NEWS_DEFAULT_MINUTE

    topics = settings.get("topics")
    if not isinstance(topics, list):
        topics = list(NEWS_DEFAULT_TOPICS)
    topics = _dedupe_topics([str(topic).strip() for topic in topics])
    if not topics:
        topics = list(NEWS_DEFAULT_TOPICS)

    subscribers = settings.get("subscribers")
    if not isinstance(subscribers, dict):
        subscribers = {}

    normalized_subscribers = {}
    for user_id, subscriber in subscribers.items():
        if not isinstance(subscriber, dict):
            continue
        user_id_text = str(user_id)
        if not user_id_text.isdigit():
            continue
        normalized_subscribers[user_id_text] = {
            "name": str(subscriber.get("name") or "알 수 없음"),
            "added_at": subscriber.get("added_at"),
            "last_sent_at": subscriber.get("last_sent_at"),
        }

    settings["hour"] = hour
    settings["minute"] = minute
    settings["topics"] = topics
    settings["subscribers"] = normalized_subscribers
    settings.setdefault("last_delivered_window_end", None)
    return settings


def _dedupe_topics(topics: list[str]) -> list[str]:
    result = []
    seen = set()
    for topic in topics:
        normalized = re.sub(r"\s+", " ", topic).strip()
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        result.append(normalized)
        seen.add(key)
    return result


def get_news_settings() -> dict:
    def mutate(all_data: dict) -> dict:
        settings = all_data.setdefault(DAILY_NEWS_KEY, _default_news_settings())
        return _normalize_news_settings(settings)

    return update_memory(mutate)


def _update_news_settings(mutator):
    def mutate(all_data: dict):
        settings = all_data.setdefault(DAILY_NEWS_KEY, _default_news_settings())
        settings = _normalize_news_settings(settings)
        result = mutator(settings)
        all_data[DAILY_NEWS_KEY] = settings
        return result

    return update_memory(mutate)


def is_special_user(user_id: int) -> bool:
    return user_id == SPECIAL_USER_ID


def is_news_command_text(user_text: str) -> bool:
    return (
        _matched_news_prefix(user_text) is not None
        or user_text == TOPIC_COMMAND_PREFIX
        or user_text.startswith(f"{TOPIC_COMMAND_PREFIX} ")
    )


def _matched_news_prefix(user_text: str) -> str | None:
    for prefix in NEWS_COMMAND_ALIASES:
        if user_text == prefix or user_text.startswith(f"{prefix} "):
            return prefix
    return None


def _strip_prefix(user_text: str, prefix: str) -> str:
    return user_text.replace(prefix, "", 1).strip()


def _subscriber_name(user: discord.User | discord.Member) -> str:
    return getattr(user, "display_name", getattr(user, "name", str(user.id)))


def _target_mentions(
    message: discord.Message,
    client_user: discord.ClientUser | discord.User | None,
) -> list[discord.User | discord.Member]:
    bot_id = getattr(client_user, "id", None)
    return [
        member
        for member in message.mentions
        if getattr(member, "id", None) is not None and member.id != bot_id
    ]


async def _fetch_user_from_text(
    client: discord.Client,
    text: str,
) -> discord.User | None:
    match = re.search(r"\b(\d{15,25})\b", text)
    if not match:
        return None

    user_id = int(match.group(1))
    cached = client.get_user(user_id)
    if cached is not None:
        return cached

    try:
        return await client.fetch_user(user_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None


async def _resolve_target_user(
    message: discord.Message,
    client: discord.Client,
    argument_text: str,
) -> discord.User | discord.Member:
    mentions = _target_mentions(message, client.user)
    if mentions:
        return mentions[0]

    fetched = await _fetch_user_from_text(client, argument_text)
    if fetched is not None:
        return fetched

    return message.author


async def _send_private(user: discord.User | discord.Member, content: str) -> bool:
    try:
        for chunk in _split_discord_message(content):
            await user.send(chunk)
        return True
    except discord.Forbidden:
        print(f"Daily news DM forbidden: {getattr(user, 'id', 'unknown')}")
        return False
    except Exception as e:
        print("Daily news DM error:", e)
        return False


async def _send_command_feedback(message: discord.Message, content: str) -> None:
    await _send_private(message.author, content)


def _split_discord_message(text: str, limit: int = NEWS_MESSAGE_LIMIT) -> list[str]:
    text = text.strip()
    if len(text) <= limit:
        return [text]

    chunks = []
    current = ""
    for block in re.split(r"(\n\n+)", text):
        if not block:
            continue

        if len(current) + len(block) <= limit:
            current += block
            continue

        if current.strip():
            chunks.append(current.strip())
            current = ""

        while len(block) > limit:
            chunks.append(block[:limit].strip())
            block = block[limit:]
        current = block

    if current.strip():
        chunks.append(current.strip())
    return chunks


def _add_subscriber(user: discord.User | discord.Member) -> bool:
    user_id = str(user.id)
    name = _subscriber_name(user)
    now = _now_kst()

    def mutate(settings: dict) -> bool:
        subscribers = settings.setdefault("subscribers", {})
        had_subscribers = bool(subscribers)
        already_exists = user_id in subscribers
        subscribers[user_id] = {
            "name": name,
            "added_at": now.isoformat(),
            "last_sent_at": subscribers.get(user_id, {}).get("last_sent_at"),
        }
        today_target = _today_schedule(now, settings["hour"], settings["minute"])
        if today_target <= now and not had_subscribers:
            settings["last_delivered_window_end"] = today_target.isoformat()
        return not already_exists

    return _update_news_settings(mutate)


def _remove_subscriber(user_id: int) -> bool:
    def mutate(settings: dict) -> bool:
        subscribers = settings.setdefault("subscribers", {})
        return subscribers.pop(str(user_id), None) is not None

    return _update_news_settings(mutate)


def _parse_delivery_time(raw_text: str) -> tuple[int, int]:
    text = raw_text.strip()
    match = re.fullmatch(
        r"(?:(오전|오후)\s*)?(\d{1,2})(?:\s*[:시]\s*(\d{1,2})?\s*분?)?",
        text,
    )
    if not match:
        raise NewsCommandError("시간은 `09:00`, `9시`, `오전 9시`처럼 적어줘.")

    period, hour_text, minute_text = match.groups()
    hour = int(hour_text)
    minute = int(minute_text) if minute_text is not None else 0

    if period is not None and not 1 <= hour <= 12:
        raise NewsCommandError("오전/오후를 붙일 때는 `오전 9시`, `오후 6시`처럼 1부터 12 사이로 적어줘.")

    if period == "오전" and hour == 12:
        hour = 0
    elif period == "오후" and hour < 12:
        hour += 12

    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise NewsCommandError("시간은 00:00부터 23:59 사이로 적어줘.")

    return hour, minute


def _set_delivery_time(hour: int, minute: int) -> None:
    now = _now_kst()
    today_target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    def mutate(settings: dict) -> None:
        settings["hour"] = hour
        settings["minute"] = minute
        if today_target <= now:
            settings["last_delivered_window_end"] = today_target.isoformat()

    _update_news_settings(mutate)


def _set_topics(topics: list[str]) -> list[str]:
    normalized_topics = _dedupe_topics(topics)
    if not normalized_topics:
        raise NewsCommandError("주제는 최소 1개는 남겨둬야 해.")

    def mutate(settings: dict) -> list[str]:
        settings["topics"] = normalized_topics
        return normalized_topics

    return _update_news_settings(mutate)


def _add_topic(topic: str) -> tuple[bool, list[str]]:
    topic = re.sub(r"\s+", " ", topic).strip()
    if not topic:
        raise NewsCommandError("추가할 주제를 적어줘. 예: `/주제 추가 강화학습`")

    def mutate(settings: dict) -> tuple[bool, list[str]]:
        topics = settings.setdefault("topics", list(NEWS_DEFAULT_TOPICS))
        before = len(topics)
        settings["topics"] = _dedupe_topics([*topics, topic])
        return len(settings["topics"]) > before, settings["topics"]

    return _update_news_settings(mutate)


def _remove_topic(topic: str) -> tuple[bool, list[str]]:
    topic = re.sub(r"\s+", " ", topic).strip()
    if not topic:
        raise NewsCommandError("제거할 주제를 적어줘. 예: `/주제 제거 인공지능`")

    def mutate(settings: dict) -> tuple[bool, list[str]]:
        topics = settings.setdefault("topics", list(NEWS_DEFAULT_TOPICS))
        kept_topics = [item for item in topics if item.casefold() != topic.casefold()]
        if not kept_topics:
            raise NewsCommandError("주제는 최소 1개는 남겨둬야 해.")
        removed = len(kept_topics) != len(topics)
        settings["topics"] = kept_topics
        return removed, kept_topics

    return _update_news_settings(mutate)


def _parse_topic_list(raw_text: str) -> list[str]:
    return _dedupe_topics(re.split(r"[,|/]+|\s{2,}", raw_text.strip()))


def _subscriber_lines(settings: dict) -> list[str]:
    subscribers = settings.get("subscribers", {})
    lines = []
    for index, (user_id, subscriber) in enumerate(subscribers.items(), start=1):
        name = subscriber.get("name", "알 수 없음")
        lines.append(f"{index}. {name} (`{user_id}`)")
    return lines


def _status_text(settings: dict, requester_id: int, full_list: bool = False) -> str:
    subscribers = settings.get("subscribers", {})
    subscribed = str(requester_id) in subscribers
    topics = ", ".join(settings.get("topics", []))
    delivery_time = _format_delivery_time(settings.get("hour", 9), settings.get("minute", 0))
    lines = [
        "최신 소식 설정이야.",
        f"- 발송 시간: 매일 {delivery_time} (한국 시간)",
        f"- 주제: {topics}",
        f"- 내 구독 상태: {'받는 중' if subscribed else '받지 않는 중'}",
    ]

    if full_list:
        subscriber_lines = _subscriber_lines(settings)
        lines.append(f"- 받는 사람 수: {len(subscribers)}명")
        lines.append("")
        lines.append("[받는 사람]")
        lines.extend(subscriber_lines or ["아직 없어."])

    return "\n".join(lines)


async def _handle_add_command(
    message: discord.Message,
    client: discord.Client,
    user_text: str,
    news_prefix: str,
    special_user: bool,
) -> None:
    argument_text = _strip_prefix(user_text, f"{news_prefix} 받기")
    target_user = await _resolve_target_user(message, client, argument_text)

    if target_user.id != message.author.id and not special_user:
        await _send_command_feedback(message, "…다른 사람을 최신 소식 목록에 추가하는 건 특별 사용자만 할 수 있어.")
        return

    settings = get_news_settings()
    delivery_time = _format_delivery_time(settings["hour"], settings["minute"])
    topics = ", ".join(settings["topics"])
    confirmation = (
        f"최신 소식을 매일 {delivery_time}에 개인 메시지로 보내줄게.\n"
        f"지금 주제는 {topics} 쪽이야."
    )

    if not await _send_private(target_user, confirmation):
        if target_user.id == message.author.id:
            print("Daily news subscription skipped because confirmation DM failed.")
        else:
            await _send_command_feedback(message, "…대상에게 개인 메시지를 보낼 수 없어서 목록에 추가하지 않았어.")
        return

    created = _add_subscriber(target_user)
    if target_user.id != message.author.id:
        status = "추가했어" if created else "이미 목록에 있었어"
        await _send_command_feedback(message, f"…{_subscriber_name(target_user)}은(는) {status}.")


async def _handle_remove_command(
    message: discord.Message,
    client: discord.Client,
    user_text: str,
    news_prefix: str,
    special_user: bool,
) -> None:
    for command in ("그만", "안받기", "해제", "제거"):
        prefix = f"{news_prefix} {command}"
        if user_text == prefix or user_text.startswith(f"{prefix} "):
            argument_text = _strip_prefix(user_text, prefix)
            break
    else:
        argument_text = ""

    target_user = await _resolve_target_user(message, client, argument_text)
    if target_user.id != message.author.id and not special_user:
        await _send_command_feedback(message, "…다른 사람을 최신 소식 목록에서 제거하는 건 특별 사용자만 할 수 있어.")
        return

    removed = _remove_subscriber(target_user.id)
    if target_user.id == message.author.id:
        if removed:
            await _send_command_feedback(message, "…응. 이제 최신 소식은 보내지 않을게.")
        else:
            await _send_command_feedback(message, "…너는 아직 최신 소식을 받고 있지 않아.")
    else:
        status = "목록에서 제거했어" if removed else "목록에 없었어"
        await _send_command_feedback(message, f"…{_subscriber_name(target_user)}은(는) {status}.")


async def _handle_time_command(
    message: discord.Message,
    user_text: str,
    news_prefix: str,
    special_user: bool,
) -> None:
    raw_text = _strip_prefix(user_text, f"{news_prefix} 시간")
    settings = get_news_settings()

    if not raw_text:
        await _send_command_feedback(
            message,
            f"…최신 소식은 매일 {_format_delivery_time(settings['hour'], settings['minute'])}에 보내고 있어.",
        )
        return

    if not special_user:
        await _send_command_feedback(message, "…발송 시간 변경은 특별 사용자만 할 수 있어.")
        return

    try:
        hour, minute = _parse_delivery_time(raw_text)
    except NewsCommandError as e:
        await _send_command_feedback(message, str(e))
        return

    _set_delivery_time(hour, minute)
    await _send_command_feedback(
        message,
        f"…최신 소식 발송 시간을 매일 {_format_delivery_time(hour, minute)}로 바꿔뒀어.",
    )


async def _handle_topic_command(
    message: discord.Message,
    user_text: str,
    special_user: bool,
) -> None:
    raw_text = _strip_prefix(user_text, TOPIC_COMMAND_PREFIX)
    settings = get_news_settings()

    if raw_text in {"", "목록"}:
        await _send_command_feedback(message, f"…지금 최신 소식 주제는 {', '.join(settings['topics'])}야.")
        return

    if not special_user:
        await _send_command_feedback(message, "…최신 소식 주제 변경은 특별 사용자만 할 수 있어.")
        return

    action, _, value = raw_text.partition(" ")
    try:
        if action == "추가":
            added, topics = _add_topic(value)
            result = "추가했어" if added else "이미 들어있어"
        elif action == "제거":
            removed, topics = _remove_topic(value)
            result = "제거했어" if removed else "목록에 없었어"
        elif action in {"설정", "변경"}:
            topics = _set_topics(_parse_topic_list(value))
            result = "이렇게 바꿔뒀어"
        else:
            await _send_command_feedback(
                message,
                "…주제 명령은 `/주제 목록`, `/주제 추가 강화학습`, `/주제 제거 인공지능`, `/주제 설정 인공지능, 프로그래밍`처럼 써줘.",
            )
            return
    except NewsCommandError as e:
        await _send_command_feedback(message, str(e))
        return

    await _send_command_feedback(message, f"…{result}.\n지금 주제: {', '.join(topics)}")


async def handle_news_command(
    message: discord.Message,
    user_text: str,
    client: discord.Client,
) -> bool:
    if not is_news_command_text(user_text):
        return False

    special_user = is_special_user(message.author.id)
    news_prefix = _matched_news_prefix(user_text)

    if news_prefix and (
        user_text == f"{news_prefix} 받기"
        or user_text.startswith(f"{news_prefix} 받기 ")
    ):
        await _handle_add_command(message, client, user_text, news_prefix, special_user)
        return True

    if news_prefix and any(
        user_text == f"{news_prefix} {command}"
        or user_text.startswith(f"{news_prefix} {command} ")
        for command in ("그만", "안받기", "해제", "제거")
    ):
        await _handle_remove_command(message, client, user_text, news_prefix, special_user)
        return True

    if news_prefix and (
        user_text == f"{news_prefix} 시간"
        or user_text.startswith(f"{news_prefix} 시간 ")
    ):
        await _handle_time_command(message, user_text, news_prefix, special_user)
        return True

    if news_prefix and user_text in {f"{news_prefix} 목록", f"{news_prefix} 상태"}:
        if special_user:
            await _send_command_feedback(message, _status_text(get_news_settings(), message.author.id, True))
        else:
            await _send_command_feedback(message, _status_text(get_news_settings(), message.author.id, False))
        return True

    if user_text == TOPIC_COMMAND_PREFIX or user_text.startswith(f"{TOPIC_COMMAND_PREFIX} "):
        await _handle_topic_command(message, user_text, special_user)
        return True

    await _send_command_feedback(
        message,
        "…최신 소식 명령은 `/최신 소식 받기`, `/최신 소식 그만`, `/최신 소식 시간`, `/최신 소식 상태`처럼 써줘.",
    )
    return True


def _today_schedule(now: datetime, hour: int, minute: int) -> datetime:
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _next_schedule_after(now: datetime, hour: int, minute: int) -> datetime:
    today = _today_schedule(now, hour, minute)
    if today > now:
        return today
    return today + timedelta(days=1)


def _due_window(settings: dict, now: datetime) -> tuple[datetime, datetime] | None:
    today = _today_schedule(now, settings["hour"], settings["minute"])
    if now < today:
        return None

    last_delivered = settings.get("last_delivered_window_end")
    if last_delivered == today.isoformat():
        return None

    return today - timedelta(days=1), today


def _mark_window_delivered(window_end: datetime) -> None:
    def mutate(settings: dict) -> None:
        settings["last_delivered_window_end"] = window_end.isoformat()
        settings["last_delivered_at"] = _now_kst().isoformat()

    _update_news_settings(mutate)


def _mark_subscriber_sent(user_id: int) -> None:
    def mutate(settings: dict) -> None:
        subscriber = settings.setdefault("subscribers", {}).get(str(user_id))
        if subscriber is not None:
            subscriber["last_sent_at"] = _now_kst().isoformat()

    _update_news_settings(mutate)


async def _send_digest_to_subscribers(
    client: discord.Client,
    report: str,
    subscribers: dict,
) -> None:
    for user_id_text in list(subscribers.keys()):
        try:
            user_id = int(user_id_text)
        except ValueError:
            continue

        user = client.get_user(user_id)
        if user is None:
            try:
                user = await client.fetch_user(user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                print(f"Daily news subscriber not reachable: {user_id}")
                continue

        sent = await _send_private(user, report)
        if sent:
            _mark_subscriber_sent(user_id)


async def deliver_daily_news(client: discord.Client) -> bool:
    settings = get_news_settings()
    subscribers = dict(settings.get("subscribers", {}))
    if not subscribers:
        return False

    now = _now_kst()
    window = _due_window(settings, now)
    if window is None:
        return False

    window_start, window_end = window
    report = await generate_daily_news_digest(
        topics=settings["topics"],
        window_start_text=_format_kst(window_start),
        window_end_text=_format_kst(window_end),
    )
    if not report:
        print("Daily news digest was not generated; delivery will be retried later.")
        return False

    await _send_digest_to_subscribers(client, report, subscribers)
    _mark_window_delivered(window_end)
    return True


async def _daily_news_loop(client: discord.Client) -> None:
    await client.wait_until_ready()

    while not client.is_closed():
        try:
            settings = get_news_settings()
            now = _now_kst()
            due = _due_window(settings, now)

            if due is not None and settings.get("subscribers"):
                delivered = await deliver_daily_news(client)
                await asyncio.sleep(60 if delivered else 300)
                continue

            next_run = _next_schedule_after(now, settings["hour"], settings["minute"])
            seconds = max(30, min((next_run - now).total_seconds(), 60))
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print("Daily news scheduler error:", e)
            await asyncio.sleep(300)


def start_daily_news_task(client: discord.Client) -> None:
    global _news_task
    if _news_task and not _news_task.done():
        return
    _news_task = asyncio.create_task(_daily_news_loop(client))


def cancel_daily_news_task() -> None:
    global _news_task
    if _news_task and not _news_task.done():
        _news_task.cancel()
    _news_task = None
