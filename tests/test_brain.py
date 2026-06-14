from firefly import brain


REQUIRED_MEMORY_FIELDS = {
    "memory_id",
    "memory_type",
    "content",
    "importance_score",
    "frequency_score",
    "created_at",
    "updated_at",
    "last_used_at",
}


def test_normalize_user_memory_migrates_legacy_brain_notes(monkeypatch):
    monkeypatch.setattr(brain, "get_current_time_text", lambda: "2026-06-14 10:00:00")
    user_data = {"brain_notes": ["짧고 확실한 답을 선호한다.", ""]}

    brain.normalize_user_memory(user_data)

    assert user_data["short_term_memory"] == []
    assert len(user_data["long_term_memory"]) == 1
    memory = user_data["long_term_memory"][0]
    assert REQUIRED_MEMORY_FIELDS <= memory.keys()
    assert memory["memory_type"] == "long_term"
    assert memory["content"] == "짧고 확실한 답을 선호한다."
    assert memory["promotion_reason"] == "legacy brain_notes migration"
    assert user_data["brain_notes"] == ["짧고 확실한 답을 선호한다."]


def test_add_brain_note_stores_short_term_candidate(monkeypatch):
    monkeypatch.setattr(brain, "get_current_time_text", lambda: "2026-06-14 10:00:00")
    user_data = {}

    result = brain.add_brain_note(user_data, "사용자는 긴 설명보다 실행 가능한 요약을 좋아한다.")

    assert result.status == "short_term"
    assert len(user_data["short_term_memory"]) == 1
    memory = user_data["short_term_memory"][0]
    assert REQUIRED_MEMORY_FIELDS <= memory.keys()
    assert memory["memory_type"] == "short_term"
    assert memory["frequency_score"] == 1
    assert user_data["long_term_memory"] == []
    assert user_data["brain_notes"] == []


def test_repeated_short_term_memory_promotes_to_long_term(monkeypatch):
    monkeypatch.setattr(brain, "get_current_time_text", lambda: "2026-06-14 10:00:00")
    user_data = {}

    brain.add_brain_note(user_data, "사용자는 긴 설명보다 실행 가능한 요약을 좋아한다.")
    brain.add_brain_note(user_data, "사용자는 긴 설명보다 실행 가능한 요약을 좋아한다.")
    result = brain.add_brain_note(user_data, "사용자는 긴 설명보다 실행 가능한 요약을 좋아한다.")

    assert result.status == "promoted"
    assert user_data["short_term_memory"] == []
    assert len(user_data["long_term_memory"]) == 1
    memory = user_data["long_term_memory"][0]
    assert memory["memory_type"] == "long_term"
    assert memory["frequency_score"] == 3
    assert "반복" in memory["promotion_reason"]
    assert user_data["brain_notes"] == ["사용자는 긴 설명보다 실행 가능한 요약을 좋아한다."]


def test_high_importance_candidate_promotes_immediately(monkeypatch):
    monkeypatch.setattr(brain, "get_current_time_text", lambda: "2026-06-14 10:00:00")
    user_data = {}

    result = brain.add_brain_note(user_data, "중요도=높음 사용자는 확인 질문을 길게 이어가는 것을 매우 싫어한다.")

    assert result.status == "promoted"
    assert user_data["short_term_memory"] == []
    memory = user_data["long_term_memory"][0]
    assert memory["importance_score"] >= brain.PROMOTION_IMPORTANCE_THRESHOLD
    assert "중요도" in memory["promotion_reason"]
    assert memory["content"] == "사용자는 확인 질문을 길게 이어가는 것을 매우 싫어한다."


def test_update_and_delete_brain_note_operate_on_long_term_memory(monkeypatch):
    monkeypatch.setattr(brain, "get_current_time_text", lambda: "2026-06-14 10:00:00")
    user_data = {}
    brain.add_brain_note(user_data, "중요도=높음 사용자는 짧고 확실한 답을 선호한다.")

    assert brain.update_brain_note(user_data, 1, "사용자는 짧고 실행 가능한 답을 선호한다.")
    deleted = brain.delete_brain_note(user_data, 1)

    assert deleted == "사용자는 짧고 실행 가능한 답을 선호한다."
    assert user_data["long_term_memory"] == []
    assert user_data["brain_notes"] == []


def test_format_brain_notes_shows_short_and_long_term_sections(monkeypatch):
    monkeypatch.setattr(brain, "get_current_time_text", lambda: "2026-06-14 10:00:00")
    user_data = {}
    brain.add_brain_note(user_data, "중요도=높음 사용자는 결론을 먼저 듣는 것을 선호한다.")
    brain.add_brain_note(user_data, "요즘 프로젝트 문서화를 자주 언급한다.")

    formatted = brain.format_brain_notes(user_data)

    assert "[장기 기억]" in formatted
    assert "[단기 기억 후보]" in formatted
    assert "결론을 먼저 듣는 것을 선호한다" in formatted
    assert "프로젝트 문서화" in formatted


def test_relationship_memory_tracks_affect_and_promotes_faster_for_sparse_profiles(monkeypatch):
    monkeypatch.setattr(brain, "get_current_time_text", lambda: "2026-06-14 10:00:00")
    user_data = {}

    first = brain.add_brain_note(user_data, "사용자는 반디에게 꾸준히 배려 깊고 신뢰를 주는 태도를 보인다.")
    second = brain.add_brain_note(user_data, "사용자는 반디에게 꾸준히 배려 깊고 신뢰를 주는 태도를 보인다.")

    assert first.status == "short_term"
    assert second.status == "promoted"
    memory = user_data["long_term_memory"][0]
    assert memory["memory_category"] == "relationship"
    assert memory["affective_score"] > 0
    assert memory["distance_score"] < 0.5
    assert "기억이 적어" in memory["promotion_reason"]


def test_dense_profiles_promote_relationship_memory_more_slowly(monkeypatch):
    monkeypatch.setattr(brain, "get_current_time_text", lambda: "2026-06-14 10:00:00")
    user_data = {"long_term_memory": [
        {"content": f"기존 장기 기억 {index}"}
        for index in range(8)
    ]}
    brain.normalize_user_memory(user_data)

    for _ in range(3):
        result = brain.add_brain_note(user_data, "사용자는 가끔 반디와 장난스럽게 거리를 좁힌다.")

    assert result.status == "short_term"
    assert len(user_data["short_term_memory"]) == 1
    assert user_data["short_term_memory"][0]["frequency_score"] == 3


def test_abrupt_relationship_change_promotes_even_for_dense_profiles(monkeypatch):
    monkeypatch.setattr(brain, "get_current_time_text", lambda: "2026-06-14 10:00:00")
    user_data = {"long_term_memory": [
        {"content": f"기존 장기 기억 {index}"}
        for index in range(8)
    ]}
    brain.normalize_user_memory(user_data)

    result = brain.add_brain_note(
        user_data,
        "감정=경계 거리감=거리둠 사용자가 갑자기 반디에게 공격적이고 불신을 주는 태도를 보였다.",
    )

    assert result.status == "promoted"
    memory = user_data["long_term_memory"][-1]
    assert memory["memory_category"] == "relationship"
    assert memory["affective_score"] < 0
    assert memory["distance_score"] > 0.7
    assert "급격한 관계 변화" in memory["promotion_reason"]
