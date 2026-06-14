import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import discord

from .config import POLLS_KEY
from .storage import load_memory, update_memory

KST = timezone(timedelta(hours=9))
POLL_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
POLL_COMMAND_FORMAT = "`/투표 제목 | 항목수=개수 | 항목1 | 항목2 | ... | 마감`"
POLL_COMMAND_EXAMPLE = "`/투표 저녁 메뉴 | 항목수=3 | 치킨 | 피자 | 떡볶이 | 10분`"
POLL_DEADLINE_HELP = (
    "마감 포맷은 상대시간 `10분`/`2시간`/`1일`/`2주`/`1달`, 시각 `23:30`, "
    "날짜시각 `2026-05-07 23:30`, ISO `2026-05-07T23:30:00+09:00` 중 하나로 적어줘. "
    "`23:30`처럼 시각만 적으면 오늘 그 시각, 이미 지났으면 내일 그 시각으로 처리해."
)
_poll_tasks: dict[str, asyncio.Task] = {}


class PollParseError(ValueError):
    pass


@dataclass
class PollSpec:
    question: str
    options: list[str]
    closes_at: datetime


@dataclass(frozen=True)
class PollCloseTarget:
    message_id: str | None
    error_message: str | None = None


LATEST_POLL_TOKENS = {"최근", "마지막", "latest", "last"}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_deadline(deadline_text: str) -> datetime:
    text = deadline_text.strip()
    text = re.sub(r"\s*(까지|동안|정도|정도로|쯤|가량|으로|로)$", "", text).strip()

    duration_match = re.fullmatch(
        r"(\d+(?:\.\d+)?)\s*(초|분|시간|일|주|주일|달|개월|s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hour|hours|d|day|days|w|week|weeks|mo|mon|month|months)",
        text,
        re.IGNORECASE,
    )
    if duration_match:
        amount = float(duration_match.group(1))
        unit = duration_match.group(2).lower()

        if unit in {"초", "s", "sec", "secs", "second", "seconds"}:
            delta = timedelta(seconds=amount)
        elif unit in {"분", "m", "min", "mins", "minute", "minutes"}:
            delta = timedelta(minutes=amount)
        elif unit in {"시간", "h", "hour", "hours"}:
            delta = timedelta(hours=amount)
        elif unit in {"일", "d", "day", "days"}:
            delta = timedelta(days=amount)
        elif unit in {"주", "주일", "w", "week", "weeks"}:
            delta = timedelta(weeks=amount)
        else:
            delta = timedelta(days=amount * 30)

        closes_at = _now_utc() + delta
        if closes_at <= _now_utc():
            raise PollParseError("마감 시간은 현재보다 뒤여야 해.")
        return closes_at

    iso_text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso_text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=KST)
        closes_at = parsed.astimezone(timezone.utc)
        if closes_at <= _now_utc():
            raise PollParseError("마감 시간은 현재보다 뒤여야 해.")
        return closes_at
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            parsed = datetime.strptime(text, fmt).replace(tzinfo=KST)
            closes_at = parsed.astimezone(timezone.utc)
            if closes_at <= _now_utc():
                raise PollParseError("마감 시간은 현재보다 뒤여야 해.")
            return closes_at
        except ValueError:
            continue

    time_match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise PollParseError("시간은 `23:30`처럼 24시간제 `HH:MM`으로 적어줘.")

        now_local = datetime.now(KST)
        parsed = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if parsed <= now_local:
            parsed += timedelta(days=1)
        return parsed.astimezone(timezone.utc)

    raise PollParseError(POLL_DEADLINE_HELP)


def _parse_option_count(text: str) -> tuple[int, bool] | None:
    normalized = text.strip().lower()
    if normalized.isdigit():
        return int(normalized), False

    count_match = re.fullmatch(r"(항목수|항목개수|개수|count)\s*[:=]?\s*(\d+)", normalized)
    if count_match:
        return int(count_match.group(2)), True

    return None


def parse_poll_command(user_text: str) -> PollSpec:
    raw = user_text.replace("/투표", "", 1).strip()
    if not raw:
        raise PollParseError(
            f"형식은 {POLL_COMMAND_FORMAT}이야.\n예: {POLL_COMMAND_EXAMPLE}\n{POLL_DEADLINE_HELP}"
        )

    parts = [part.strip() for part in raw.split("|") if part.strip()]
    if len(parts) < 4:
        raise PollParseError(
            f"형식은 {POLL_COMMAND_FORMAT}이야. 항목은 최소 2개가 필요해.\n"
            f"예: {POLL_COMMAND_EXAMPLE}\n{POLL_DEADLINE_HELP}"
        )

    question = parts[0]
    expected_option_count = None
    parsed_option_count = _parse_option_count(parts[1])

    if parsed_option_count is not None:
        count, explicit_count = parsed_option_count
        if explicit_count or (2 <= count <= len(POLL_EMOJIS) and len(parts) == count + 3):
            expected_option_count = count

    if expected_option_count is not None:
        options = parts[2:-1]
    else:
        options = parts[1:-1]

    deadline_text = parts[-1]

    if not question:
        raise PollParseError("투표 제목을 적어줘.")
    if len(question) > 256:
        raise PollParseError("투표 제목은 256자 이하로 적어줘.")

    if expected_option_count is not None and not 2 <= expected_option_count <= len(POLL_EMOJIS):
        raise PollParseError(f"항목수는 2부터 {len(POLL_EMOJIS)}까지 가능해.")

    if not 2 <= len(options) <= len(POLL_EMOJIS):
        raise PollParseError(f"투표 항목은 2개부터 {len(POLL_EMOJIS)}개까지 가능해.")

    if expected_option_count is not None and len(options) != expected_option_count:
        raise PollParseError(
            f"항목수를 {expected_option_count}개로 적었지만 실제 항목은 {len(options)}개야. "
            f"형식은 {POLL_COMMAND_FORMAT}이야."
        )

    normalized_options = []
    for option in options:
        if len(option) > 100:
            raise PollParseError("각 투표 항목은 100자 이하로 적어줘.")
        normalized_options.append(option)

    return PollSpec(
        question=question,
        options=normalized_options,
        closes_at=_parse_deadline(deadline_text),
    )


def _active_polls() -> dict:
    return load_memory().get(POLLS_KEY, {})


def _save_poll(poll: dict) -> None:
    def mutate(all_data: dict) -> None:
        all_data.setdefault(POLLS_KEY, {})[str(poll["message_id"])] = poll

    update_memory(mutate)


def get_poll(message_id: int | str) -> dict | None:
    all_data = load_memory()
    return all_data.get(POLLS_KEY, {}).get(str(message_id))


def remove_poll(message_id: int | str) -> None:
    def mutate(all_data: dict) -> None:
        polls = all_data.setdefault(POLLS_KEY, {})
        polls.pop(str(message_id), None)

    update_memory(mutate)


def _extract_poll_close_message_id(user_text: str) -> str | None:
    raw = user_text.replace("/투표마감", "", 1).strip()
    match = re.search(r"\b\d+\b", raw)
    return match.group(0) if match else None


def _wants_latest_poll(user_text: str) -> bool:
    raw = user_text.replace("/투표마감", "", 1).strip().lower()
    return raw in LATEST_POLL_TOKENS


def _poll_message_id_sort_key(poll: dict) -> int:
    try:
        return int(poll.get("message_id", 0))
    except (TypeError, ValueError):
        return 0


def _active_polls_in_channel(channel_id: int | str) -> list[dict]:
    channel_id_text = str(channel_id)
    polls = [
        poll
        for poll in _active_polls().values()
        if str(poll.get("channel_id")) == channel_id_text
    ]
    return sorted(polls, key=_poll_message_id_sort_key, reverse=True)


def _resolve_poll_close_target(message: discord.Message, user_text: str) -> PollCloseTarget:
    explicit_message_id = _extract_poll_close_message_id(user_text)
    if explicit_message_id:
        return PollCloseTarget(explicit_message_id)

    reference = getattr(message, "reference", None)
    reference_message_id = getattr(reference, "message_id", None)
    if reference_message_id is not None:
        return PollCloseTarget(str(reference_message_id))

    channel_id = getattr(getattr(message, "channel", None), "id", None)
    if channel_id is None:
        return PollCloseTarget(
            None,
            "…마감할 투표 메시지에 답장하거나 `/투표마감 메시지ID`로 알려줘.",
        )

    channel_polls = _active_polls_in_channel(channel_id)
    if not channel_polls:
        return PollCloseTarget(None, "…이 채널에 진행 중인 투표가 없어.")

    if len(channel_polls) == 1 or _wants_latest_poll(user_text):
        return PollCloseTarget(str(channel_polls[0]["message_id"]))

    return PollCloseTarget(
        None,
        "…진행 중인 투표가 여러 개야. 마감할 투표 메시지에 답장하거나 `/투표마감 메시지ID`로 알려줘.",
    )


def _cancel_poll_task(message_id: int | str) -> None:
    task = _poll_tasks.pop(str(message_id), None)
    if task and not task.done():
        task.cancel()


def _discord_timestamp(closes_at: datetime, style: str = "F") -> str:
    return f"<t:{int(closes_at.timestamp())}:{style}>"


def _missing_poll_permissions(message: discord.Message) -> list[str]:
    guild = getattr(message, "guild", None)
    channel = getattr(message, "channel", None)
    bot_member = getattr(guild, "me", None)

    if guild is None or bot_member is None or not hasattr(channel, "permissions_for"):
        return []

    permissions = channel.permissions_for(bot_member)
    required_permissions = (
        ("send_messages", "메시지 보내기"),
        ("add_reactions", "반응 추가"),
        ("read_message_history", "메시지 기록 보기"),
        ("mention_everyone", "@everyone 멘션"),
    )
    return [
        label
        for attr, label in required_permissions
        if hasattr(permissions, attr) and not getattr(permissions, attr)
    ]


def _everyone_allowed_mentions():
    allowed_mentions = getattr(discord, "AllowedMentions", None)
    if allowed_mentions is None:
        return None
    return allowed_mentions(everyone=True)


def create_poll_embed(
    question: str,
    options: list[str],
    closes_at: datetime,
    author_name: str,
    closed: bool = False,
    closed_by: str | None = None,
    closed_at: datetime | None = None,
    total_votes: int | None = None,
) -> discord.Embed:
    lines = [f"{POLL_EMOJIS[i]} {option}" for i, option in enumerate(options)]
    embed = discord.Embed(
        title=("투표 종료" if closed else "투표"),
        description="\n".join(lines),
        color=0x00FFFF if not closed else 0x888888,
    )
    embed.add_field(name="주제", value=question, inline=False)
    if closed:
        embed.add_field(
            name="종료",
            value=_discord_timestamp(closed_at or closes_at),
            inline=False,
        )
    else:
        embed.add_field(
            name="마감",
            value=f"{_discord_timestamp(closes_at)} ({_discord_timestamp(closes_at, 'R')})",
            inline=False,
        )
    if closed_by:
        embed.add_field(name="상태", value=f"{closed_by}님이 조기 마감함", inline=False)
    if total_votes is not None:
        prefix = "총" if closed else "현재"
        embed.add_field(name="참여", value=f"{prefix} {total_votes}명", inline=False)
    embed.set_footer(text=f"생성자: {author_name} · 한 사람당 하나의 반응만 집계")
    return embed


def create_result_embed(
    poll: dict,
    counts: list[int],
    total_votes: int,
    closed_by: str | None = None,
) -> discord.Embed:
    options = poll["options"]
    max_votes = max(counts) if counts else 0
    winners = [
        options[index]
        for index, count in enumerate(counts)
        if count == max_votes and max_votes > 0
    ]

    embed = discord.Embed(
        title="투표 결과",
        description=poll["question"],
        color=0x00FFFF,
    )

    for index, option in enumerate(options):
        count = counts[index]
        percent = 0 if total_votes == 0 else round(count / total_votes * 100, 1)
        embed.add_field(
            name=f"{POLL_EMOJIS[index]} {option}",
            value=f"{count}표 ({percent}%)",
            inline=False,
        )

    result_text = "투표가 없었어." if not winners else " / ".join(winners)
    embed.add_field(name="최다 득표", value=result_text, inline=False)
    footer_text = f"총 {total_votes}표"
    if closed_by:
        footer_text += f" · 조기 마감: {closed_by}"
    embed.set_footer(text=footer_text)
    return embed


async def create_poll_from_command(
    message: discord.Message,
    user_text: str,
    client: discord.Client,
) -> None:
    try:
        spec = parse_poll_command(user_text)
    except PollParseError as e:
        await message.channel.send(str(e))
        return

    missing_permissions = _missing_poll_permissions(message)
    if missing_permissions:
        await message.channel.send(
            "…투표를 열려면 봇에게 이 권한이 필요해: "
            + ", ".join(missing_permissions)
        )
        return

    author_name = getattr(message.author, "display_name", message.author.name)
    embed = create_poll_embed(
        question=spec.question,
        options=spec.options,
        closes_at=spec.closes_at,
        author_name=author_name,
        total_votes=0,
    )
    send_kwargs = {
        "content": "@everyone",
        "embed": embed,
    }
    allowed_mentions = _everyone_allowed_mentions()
    if allowed_mentions is not None:
        send_kwargs["allowed_mentions"] = allowed_mentions

    poll_message = await message.channel.send(**send_kwargs)

    try:
        for emoji in POLL_EMOJIS[: len(spec.options)]:
            await poll_message.add_reaction(emoji)
    except discord.Forbidden:
        try:
            await poll_message.delete()
        except (discord.Forbidden, discord.NotFound):
            pass
        await message.channel.send("…반응을 추가할 권한이 없어서 투표를 열 수 없어.")
        return

    poll = {
        "message_id": poll_message.id,
        "channel_id": poll_message.channel.id,
        "guild_id": message.guild.id if message.guild else None,
        "question": spec.question,
        "options": spec.options,
        "author_id": message.author.id,
        "author_name": author_name,
        "closes_at": spec.closes_at.isoformat(),
    }
    _save_poll(poll)
    schedule_poll(client, poll)


async def _fetch_poll_message(client: discord.Client, poll: dict) -> discord.Message | None:
    channel = client.get_channel(int(poll["channel_id"]))
    if channel is None:
        channel = await client.fetch_channel(int(poll["channel_id"]))
    return await channel.fetch_message(int(poll["message_id"]))


async def tally_poll_votes(poll_message: discord.Message, option_count: int) -> tuple[list[int], int]:
    votes_by_option = [set() for _ in range(option_count)]
    counted_users = set()

    for index, emoji in enumerate(POLL_EMOJIS[:option_count]):
        reaction = next((item for item in poll_message.reactions if str(item.emoji) == emoji), None)
        if reaction is None:
            continue

        async for user in reaction.users():
            if user.bot or user.id in counted_users:
                continue
            counted_users.add(user.id)
            votes_by_option[index].add(user.id)

    counts = [len(voters) for voters in votes_by_option]
    return counts, len(counted_users)


async def refresh_poll_vote_count(
    client: discord.Client,
    payload: discord.RawReactionActionEvent,
) -> None:
    if client.user and payload.user_id == client.user.id:
        return

    poll = get_poll(payload.message_id)
    if not poll:
        return

    if str(payload.emoji) not in set(POLL_EMOJIS[: len(poll["options"])]):
        return

    try:
        poll_message = await _fetch_poll_message(client, poll)
        _, total_votes = await tally_poll_votes(poll_message, len(poll["options"]))
        poll = get_poll(payload.message_id)
        if not poll:
            return

        closes_at = datetime.fromisoformat(poll["closes_at"])
        embed = create_poll_embed(
            question=poll["question"],
            options=poll["options"],
            closes_at=closes_at,
            author_name=poll.get("author_name", "알 수 없음"),
            total_votes=total_votes,
        )
        await poll_message.edit(embed=embed)
    except (discord.NotFound, discord.Forbidden):
        return
    except Exception as e:
        print("Poll count refresh error:", e)


async def finalize_poll(
    client: discord.Client,
    message_id: int | str,
    closed_by: str | None = None,
) -> bool:
    poll = get_poll(message_id)
    if not poll:
        return False

    remove_poll(message_id)
    _poll_tasks.pop(str(message_id), None)
    finalized = False

    try:
        poll_message = await _fetch_poll_message(client, poll)
        counts, total_votes = await tally_poll_votes(poll_message, len(poll["options"]))
        closes_at = datetime.fromisoformat(poll["closes_at"])

        closed_embed = create_poll_embed(
            question=poll["question"],
            options=poll["options"],
            closes_at=closes_at,
            author_name=poll.get("author_name", "알 수 없음"),
            closed=True,
            closed_by=closed_by,
            closed_at=_now_utc() if closed_by else closes_at,
            total_votes=total_votes,
        )
        await poll_message.edit(embed=closed_embed)
        await poll_message.channel.send(
            embed=create_result_embed(poll, counts, total_votes, closed_by)
        )
        finalized = True
    except discord.NotFound:
        pass
    except discord.Forbidden:
        pass
    except Exception as e:
        print("Poll finalize error:", e)
    finally:
        _poll_tasks.pop(str(message_id), None)
    return finalized


async def close_poll_from_command(
    message: discord.Message,
    client: discord.Client,
    user_text: str = "/투표마감",
) -> None:
    target = _resolve_poll_close_target(message, user_text)
    if target.error_message:
        await message.channel.send(target.error_message)
        return

    message_id = target.message_id
    poll = get_poll(message_id)
    if not poll:
        await message.channel.send("…진행 중인 투표를 찾지 못했어.")
        return

    if int(poll["channel_id"]) != message.channel.id:
        await message.channel.send("…투표가 열린 채널에서 답장으로 마감해줘.")
        return

    closed_by = getattr(message.author, "display_name", message.author.name)
    _cancel_poll_task(message_id)
    closed = await finalize_poll(client, message_id, closed_by=closed_by)
    if not closed:
        await message.channel.send(
            "…투표를 마감하려 했지만 메시지를 찾지 못했거나 권한이 부족했어. 저장된 투표 예약은 정리했어."
        )


async def _poll_countdown(client: discord.Client, poll: dict) -> None:
    message_id = str(poll["message_id"])

    while get_poll(message_id):
        closes_at = datetime.fromisoformat(poll["closes_at"])
        seconds = (closes_at - _now_utc()).total_seconds()
        if seconds <= 0:
            await finalize_poll(client, message_id)
            return
        await asyncio.sleep(min(seconds, 3600))


def schedule_poll(client: discord.Client, poll: dict) -> None:
    message_id = str(poll["message_id"])
    current_task = _poll_tasks.get(message_id)
    if current_task and not current_task.done():
        return
    _poll_tasks[message_id] = asyncio.create_task(_poll_countdown(client, poll))


def cancel_poll_tasks() -> None:
    for task in _poll_tasks.values():
        if not task.done():
            task.cancel()
    _poll_tasks.clear()


async def restore_poll_tasks(client: discord.Client) -> None:
    for poll in list(_active_polls().values()):
        if datetime.fromisoformat(poll["closes_at"]) <= _now_utc():
            asyncio.create_task(finalize_poll(client, poll["message_id"]))
        else:
            schedule_poll(client, poll)


async def enforce_single_vote(
    client: discord.Client,
    payload: discord.RawReactionActionEvent,
) -> None:
    if client.user and payload.user_id == client.user.id:
        return

    poll = get_poll(payload.message_id)
    if not poll:
        return

    selected_emoji = str(payload.emoji)
    valid_emojis = set(POLL_EMOJIS[: len(poll["options"])])
    if selected_emoji not in valid_emojis:
        return

    try:
        channel = client.get_channel(payload.channel_id)
        if channel is None:
            channel = await client.fetch_channel(payload.channel_id)

        poll_message = await channel.fetch_message(payload.message_id)
        user = payload.member or await client.fetch_user(payload.user_id)
        if user.bot:
            return

        for reaction in poll_message.reactions:
            reaction_emoji = str(reaction.emoji)
            if reaction_emoji in valid_emojis and reaction_emoji != selected_emoji:
                await reaction.remove(user)

        await refresh_poll_vote_count(client, payload)
    except (discord.NotFound, discord.Forbidden):
        return
    except Exception as e:
        print("Poll vote cleanup error:", e)
