from firefly.embeds import create_special_help_embed


def _field_text(embed):
    return "\n".join(f"{field.name}\n{field.value}" for field in embed.fields)


def test_special_help_lists_voice_search_and_admin_status_commands():
    text = _field_text(create_special_help_embed())

    assert "/기록검색 [파일명] 질문" in text
    assert "/녹음검색 [파일명] 질문" in text
    assert "/봇상태" in text
    assert "/관리상태" in text


def test_special_help_keeps_poll_help_short():
    text = _field_text(create_special_help_embed())

    assert "`10분`" in text
    assert "`2시간`" in text
    assert "`23:30`" in text
    assert "ISO" not in text
