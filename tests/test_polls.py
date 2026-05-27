import asyncio
from types import SimpleNamespace

import pytest

from firefly import polls
from firefly.polls import PollParseError, parse_poll_command


def test_parse_poll_command_accepts_four_options_with_explicit_count():
    spec = parse_poll_command(
        "/투표 반디랑 갈 데이트 장소 | 항목수=4 | 조용한 북카페 | "
        "한적한 공원 산책길 | 작은 수족관 | 야경 보이는 강변 | 10분"
    )

    assert spec.question == "반디랑 갈 데이트 장소"
    assert spec.options == [
        "조용한 북카페",
        "한적한 공원 산책길",
        "작은 수족관",
        "야경 보이는 강변",
    ]


def test_parse_poll_command_rejects_count_mismatch():
    with pytest.raises(PollParseError, match="항목수를 4개로 적었지만 실제 항목은 3개"):
        parse_poll_command(
            "/투표 데이트 장소 | 항목수=4 | 북카페 | 공원 | 수족관 | 10분"
        )


def test_poll_close_target_uses_only_active_poll_in_current_channel(monkeypatch):
    active_poll = {"message_id": "200", "channel_id": "10"}
    message = SimpleNamespace(channel=SimpleNamespace(id=10), reference=None)
    monkeypatch.setattr(polls, "_active_polls", lambda: {"200": active_poll})

    target = polls._resolve_poll_close_target(message, "/투표마감")

    assert target.message_id == "200"
    assert target.error_message is None


def test_poll_close_target_requires_id_when_multiple_polls_are_active(monkeypatch):
    message = SimpleNamespace(channel=SimpleNamespace(id=10), reference=None)
    monkeypatch.setattr(
        polls,
        "_active_polls",
        lambda: {
            "200": {"message_id": "200", "channel_id": "10"},
            "201": {"message_id": "201", "channel_id": "10"},
        },
    )

    target = polls._resolve_poll_close_target(message, "/투표마감")

    assert target.message_id is None
    assert "여러 개" in target.error_message


def test_poll_close_target_supports_latest_alias_with_multiple_polls(monkeypatch):
    message = SimpleNamespace(channel=SimpleNamespace(id=10), reference=None)
    monkeypatch.setattr(
        polls,
        "_active_polls",
        lambda: {
            "200": {"message_id": "200", "channel_id": "10"},
            "201": {"message_id": "201", "channel_id": "10"},
        },
    )

    target = polls._resolve_poll_close_target(message, "/투표마감 최근")

    assert target.message_id == "201"
    assert target.error_message is None


def test_poll_close_command_closes_active_channel_poll_without_reply(monkeypatch):
    sent_messages = []
    finalized = []
    active_poll = {"message_id": "200", "channel_id": "10"}

    class FakeChannel:
        id = 10

        async def send(self, content=None, **kwargs):
            sent_messages.append(content or "<embed>")

    async def fake_finalize_poll(client, message_id, closed_by=None):
        finalized.append((str(message_id), closed_by))
        return True

    monkeypatch.setattr(polls, "_active_polls", lambda: {"200": active_poll})
    monkeypatch.setattr(
        polls,
        "get_poll",
        lambda message_id: active_poll if str(message_id) == "200" else None,
    )
    monkeypatch.setattr(polls, "finalize_poll", fake_finalize_poll)

    message = SimpleNamespace(
        author=SimpleNamespace(display_name="Owner", name="Owner"),
        channel=FakeChannel(),
        reference=None,
    )

    asyncio.run(polls.close_poll_from_command(message, object(), "/투표마감"))

    assert sent_messages == []
    assert finalized == [("200", "Owner")]
