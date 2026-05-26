import asyncio
from datetime import datetime

from firefly import news


def test_deliver_daily_news_tries_broad_search_when_initial_items_are_duplicates(monkeypatch):
    settings = {
        "hour": 9,
        "minute": 0,
        "topics": ["인공지능", "프로그래밍"],
        "subscribers": {"123": {"name": "상범"}},
        "delivered_items": [
            {
                "title": "이미 보낸 소식",
                "url": "https://example.com/already-sent",
            }
        ],
        "last_delivered_window_end": "2026-05-25T09:00:00+09:00",
    }
    calls = []
    sent_reports = []
    delivered_reports = []

    async def fake_generate_daily_news_digest(*, broaden_search=False, **kwargs):
        calls.append(broaden_search)
        if not broaden_search:
            return """
2026-05-25 09:00부터 2026-05-26 09:00까지, 주제: 인공지능, 프로그래밍

[1] 이미 보낸 소식
- 무슨 일: 이미 전달한 링크와 같은 소식이야.
- 확인 링크:
  https://example.com/already-sent
""".strip()

        return """
2026-05-25 09:00부터 2026-05-26 09:00까지, 주제: 인공지능, 프로그래밍

[1] 새 논문 동향
- 무슨 일: 보강 검색에서 확인한 새 자료야.
- 확인 링크:
  https://example.com/new-paper
""".strip()

    async def fake_resolve_news_recipients(client, subscribers):
        return [(123, object())]

    async def fake_send_digest_to_subscribers(report, recipients):
        sent_reports.append(report)
        return 1

    def fake_mark_window_delivered(window_end, report):
        delivered_reports.append(report)

    monkeypatch.setattr(news, "_now_kst", lambda: datetime(2026, 5, 26, 9, 1, tzinfo=news.KST))
    monkeypatch.setattr(news, "get_news_settings", lambda: settings)
    monkeypatch.setattr(news, "generate_daily_news_digest", fake_generate_daily_news_digest)
    monkeypatch.setattr(news, "_resolve_news_recipients", fake_resolve_news_recipients)
    monkeypatch.setattr(news, "_send_digest_to_subscribers", fake_send_digest_to_subscribers)
    monkeypatch.setattr(news, "_mark_window_delivered", fake_mark_window_delivered)

    delivered = asyncio.run(news.deliver_daily_news(object()))

    assert delivered is True
    assert calls == [False, True]
    assert len(sent_reports) == 1
    assert "새 논문 동향" in sent_reports[0]
    assert "이미 보낸 소식" not in sent_reports[0]
    assert delivered_reports == sent_reports
