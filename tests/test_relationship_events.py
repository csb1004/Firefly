from datetime import datetime, timedelta

from firefly.relationship_events import (
    RELATIONSHIP_EVENTS_KEY,
    build_relationship_event_context,
    normalize_relationship_events,
)


def test_relationship_events_initialize_minimal_state():
    user_data = {}
    now = datetime(2026, 5, 20, 12, 0, 0)

    events = normalize_relationship_events(user_data, now)

    assert user_data[RELATIONSHIP_EVENTS_KEY] is events
    assert events["first_seen_date"] == "2026-05-20"
    assert events["recent_topic"] is None


def test_inactivity_event_fires_once_per_day():
    now = datetime(2026, 5, 20, 12, 0, 0)
    user_data = {"last_seen": (now - timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S")}

    first = build_relationship_event_context(user_data, "오랜만이야", now=now)
    second = build_relationship_event_context(user_data, "또 말 걸기", now=now)

    assert "away" in first
    assert "away" not in second


def test_recent_topic_is_recorded_and_reused():
    now = datetime(2026, 5, 20, 12, 0, 0)
    user_data = {}

    build_relationship_event_context(user_data, "오늘 파스타 먹으러 가자", now=now)
    context = build_relationship_event_context(user_data, "아까 그 얘기 이어서", now=now)

    assert "파스타" in context
