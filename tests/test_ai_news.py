from firefly.ai import build_daily_news_digest_prompt


def test_daily_news_prompt_includes_broad_source_categories():
    system_prompt, user_prompt = build_daily_news_digest_prompt(
        topics=["인공지능", "프로그래밍"],
        window_start_text="2026-05-25 09:00",
        window_end_text="2026-05-26 09:00",
    )

    assert "[선정 우선순위]" in user_prompt
    assert "[제외 신호]" in user_prompt
    assert "주요 언론, 공식 발표" in user_prompt
    assert "GitHub 저장소의 개별 PR/이슈" in user_prompt
    assert "GitHub Copilot, IDE, 개발자 도구의 사소한 기능 추가" in user_prompt
    assert "단순 업데이트는 전하지 않는다" in user_prompt
    assert "GitHub 단순 업데이트는 제외" in user_prompt
    assert "arXiv" in user_prompt
    assert "OpenReview" in user_prompt
    assert "NeurIPS" in user_prompt
    assert "CVPR" in user_prompt
    assert "Hugging Face Papers" in user_prompt
    assert "CVE/NVD" in user_prompt
    assert "서울경제" in user_prompt
    assert "안될공학" in user_prompt
    assert "GitHub Copilot이나 IDE의 사소한 기능 추가 같은 단순 업데이트 소식은 전하지 않는다" in system_prompt


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
