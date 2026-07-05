from firefly import brain


def test_normalize_user_memory_migrates_legacy_brain_notes_to_keyword_scores(monkeypatch):
    monkeypatch.setattr(brain, "get_current_time_text", lambda: "2026-06-14 10:00:00")
    user_data = {"brain_notes": ["짧고 확실한 답을 선호한다.", ""]}

    brain.normalize_user_memory(user_data)

    assert user_data["brain_keywords"] == {"짧은답변선호": 3.0}
    assert user_data["brain_notes"] == ["짧은답변선호: 3"]
    assert user_data["short_term_memory"] == []
    assert user_data["long_term_memory"] == []
    assert user_data["memory_stats"]["schema_version"] == brain.MEMORY_SCHEMA_VERSION


def test_add_brain_note_stores_keyword_score_dictionary(monkeypatch):
    monkeypatch.setattr(brain, "get_current_time_text", lambda: "2026-06-14 10:00:00")
    user_data = {}

    result = brain.add_brain_note(user_data, "애정표현: 3 | 기쁨: 2")

    assert result.status == "updated"
    assert user_data["brain_keywords"] == {"애정표현": 3.0, "기쁨": 2.0}
    assert user_data["brain_notes"] == ["애정표현: 3", "기쁨: 2"]
    assert result.entry["updated_scores"] == {"애정표현": 3.0, "기쁨": 2.0}


def test_add_brain_note_applies_discount_before_accumulating(monkeypatch):
    monkeypatch.setattr(brain, "get_current_time_text", lambda: "2026-06-14 10:00:00")
    user_data = {}

    brain.add_brain_note(user_data, "애정표현: 5")
    result = brain.add_brain_note(user_data, "애정표현: 5 | 서운함: 2")

    assert result.status == "updated"
    assert user_data["brain_keywords"]["애정표현"] == 9.5
    assert user_data["brain_keywords"]["서운함"] == 2.0
    assert "할인률" in result.reason


def test_keyword_input_score_is_clamped_to_one_to_five(monkeypatch):
    monkeypatch.setattr(brain, "get_current_time_text", lambda: "2026-06-14 10:00:00")
    user_data = {}

    brain.add_brain_note(user_data, "기쁨: 10 | 서운함: -2")

    assert user_data["brain_keywords"] == {"기쁨": 5.0, "서운함": 1.0}


def test_similar_keyword_aliases_merge_to_canonical_keyword(monkeypatch):
    monkeypatch.setattr(brain, "get_current_time_text", lambda: "2026-06-14 10:00:00")
    user_data = {}

    brain.add_brain_note(user_data, "사랑: 4")
    brain.add_brain_note(user_data, "호감: 3")

    assert user_data["brain_keywords"] == {"애정표현": 6.6}


def test_natural_text_fallback_derives_known_keyword(monkeypatch):
    monkeypatch.setattr(brain, "get_current_time_text", lambda: "2026-06-14 10:00:00")
    user_data = {}

    result = brain.add_brain_note(user_data, "사용자는 반디에게 고마워라고 말했다.")

    assert result.status == "updated"
    assert user_data["brain_keywords"] == {"감사": 2.0}


def test_update_and_delete_brain_keyword_by_number(monkeypatch):
    monkeypatch.setattr(brain, "get_current_time_text", lambda: "2026-06-14 10:00:00")
    user_data = {}
    brain.add_brain_note(user_data, "애정표현: 3 | 기쁨: 2")

    assert brain.update_brain_note(user_data, 1, "애정표현: 8")
    deleted = brain.delete_brain_note(user_data, 1)

    assert deleted == "애정표현: 8"
    assert user_data["brain_keywords"] == {"기쁨": 2.0}
    assert user_data["brain_notes"] == ["기쁨: 2"]


def test_delete_brain_memory_accepts_keyword_name(monkeypatch):
    monkeypatch.setattr(brain, "get_current_time_text", lambda: "2026-06-14 10:00:00")
    user_data = {}
    brain.add_brain_note(user_data, "애정표현: 3 | 서운함: 2")

    result = brain.delete_brain_memory(user_data, brain.parse_brain_delete_target("애정표현"))

    assert result is not None
    assert result.memory_type == brain.BRAIN_KEYWORDS_KEY
    assert result.contents == ["애정표현: 3"]
    assert user_data["brain_keywords"] == {"서운함": 2.0}


def test_format_brain_notes_shows_keyword_dictionary(monkeypatch):
    monkeypatch.setattr(brain, "get_current_time_text", lambda: "2026-06-14 10:00:00")
    user_data = {}
    brain.add_brain_note(user_data, "애정표현: 5 | 기쁨: 3 | 서운함: 2")

    formatted = brain.format_brain_notes(user_data)

    assert "[키워드 점수 딕셔너리]" in formatted
    assert "애정표현: 5 | 기쁨: 3 | 서운함: 2" in formatted
    assert "할인률 0.90" in formatted
