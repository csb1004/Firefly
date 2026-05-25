import pytest

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
