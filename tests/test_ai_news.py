from firefly.ai import build_daily_news_digest_prompt


def test_daily_news_prompt_includes_broad_source_categories():
    _, user_prompt = build_daily_news_digest_prompt(
        topics=["인공지능", "프로그래밍"],
        window_start_text="2026-05-25 09:00",
        window_end_text="2026-05-26 09:00",
    )

    assert "GitHub나 일반 뉴스 검색 한두 곳에서 멈추지 말고" in user_prompt
    assert "arXiv" in user_prompt
    assert "OpenReview" in user_prompt
    assert "NeurIPS" in user_prompt
    assert "CVPR" in user_prompt
    assert "Hugging Face Papers" in user_prompt
    assert "CVE/NVD" in user_prompt
    assert "서울경제" in user_prompt
    assert "안될공학" in user_prompt


def test_daily_news_prompt_adds_broad_search_fallback_mode():
    _, user_prompt = build_daily_news_digest_prompt(
        topics=["인공지능"],
        window_start_text="2026-05-25 09:00",
        window_end_text="2026-05-26 09:00",
        previously_sent_items=["이미 보낸 논문 | https://example.com/old"],
        broaden_search=True,
    )

    assert "[보강 검색 모드]" in user_prompt
    assert "최근 7일 이내" in user_prompt
    assert "이미 보낸 논문 | https://example.com/old" in user_prompt
