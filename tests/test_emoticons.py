from firefly import emoticons


def test_parse_reply_emoticon_strips_final_marker():
    parsed = emoticons.parse_reply_emoticon("고마워.\n[[EMOTICON: pom_heart]]")

    assert parsed.text == "고마워."
    assert parsed.emoticon_key == "pom_heart"


def test_parse_reply_emoticon_accepts_none_and_ignores_unknown_keys():
    none_parsed = emoticons.parse_reply_emoticon("차분하게 답할게.\n[[EMOTICON: none]]")
    unknown_parsed = emoticons.parse_reply_emoticon("차분하게 답할게.\n[[EMOTICON: unknown]]")

    assert none_parsed.text == "차분하게 답할게."
    assert none_parsed.emoticon_key is None
    assert unknown_parsed.text == "차분하게 답할게."
    assert unknown_parsed.emoticon_key is None


def test_parse_reply_emoticon_resolves_legacy_key_aliases():
    parsed = emoticons.parse_reply_emoticon("앗, 가격이...\n[[EMOTICON: bandi_sorry]]")

    assert parsed.text == "앗, 가격이..."
    assert parsed.emoticon_key == "bandi_wallet_blank"


def test_emoticon_prompt_lists_distinct_keys_and_marker_rule():
    prompt = emoticons.build_emoticon_prompt()

    assert "[[EMOTICON: none]]" in prompt
    assert "`bandi_gentle`" in prompt
    assert "`bandi_wallet_blank`" in prompt
    assert "`ghost_protest`" in prompt
    assert "`pom_awkward`" in prompt
    assert "`sam_ready`" in prompt
    assert "`pom_shy`" in prompt
    assert "`bandi_sorry`" not in prompt
    assert "봇 명령어 한 줄만 출력해야 하는 경우에는 이모티콘 줄을 붙이지 않는다" in prompt
