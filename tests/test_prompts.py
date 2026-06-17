from firefly import prompts
from firefly.config import TOOL_PLANNER_PROMPT_FILE


def test_build_model_history_keeps_recent_chat_messages_and_skips_commands(monkeypatch):
    monkeypatch.setattr(prompts, "MAX_MODEL_HISTORY", 3)
    history = [
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "/help"},
        {"role": "system", "content": "ignore"},
        {"role": "user", "content": "new"},
    ]

    assert prompts.build_model_history(history) == [
        {"role": "user", "content": "new"},
    ]


def test_build_room_model_history_adds_user_metadata_and_skips_commands(monkeypatch):
    monkeypatch.setattr(prompts, "MAX_ROOM_MODEL_HISTORY", 4)
    room_history = [
        {"role": "user", "speaker": "Alice", "content": "hello", "nickname": "Al", "affection": 60},
        {"role": "assistant", "content": "hi"},
        {"role": "user", "speaker": "Bob", "content": "/help"},
        {"role": "assistant", "content": "still here"},
    ]

    model_history = prompts.build_room_model_history(room_history)

    assert model_history[0]["role"] == "user"
    assert "Alice" in model_history[0]["content"]
    assert "Al" in model_history[0]["content"]
    assert "60" in model_history[0]["content"]
    assert model_history[0]["content"].endswith("hello")
    assert model_history[1:] == [
        {"role": "assistant", "content": "hi"},
        {"role": "assistant", "content": "still here"},
    ]


def test_build_group_context_prompt_includes_current_user_and_recent_participants():
    prompt = prompts.build_group_context_prompt(
        display_name="Current",
        user_id=3,
        user_data={"nickname": "Cur", "affection": 70},
        room_data={
            "history": [
                {"role": "user", "user_id": 1, "speaker": "Alice", "nickname": "Al", "affection": 60},
                {"role": "assistant", "speaker": "Bot", "content": "hello"},
                {"role": "user", "user_id": 2, "speaker": "Bob", "nickname": "B", "affection": 40},
            ]
        },
    )

    assert "Current" in prompt
    assert "Cur" in prompt
    assert "70" in prompt
    assert "Alice" in prompt
    assert "Bob" in prompt


def test_build_system_prompt_uses_base_prompt_user_state_and_time(monkeypatch):
    monkeypatch.setattr(prompts, "get_base_prompt", lambda user_id: f"base prompt for {user_id}")
    monkeypatch.setattr(prompts, "load_text_file", lambda path: "general command guide")
    monkeypatch.setattr(prompts, "get_current_time_text", lambda: "2026-05-16 12:00:00")

    prompt = prompts.build_system_prompt(
        123,
        {
            "name": "Alice",
            "nickname": "Al",
            "affection": 50,
            "last_seen": "yesterday",
            "brain_notes": ["짧고 확실한 답을 선호한다."],
        },
    )

    assert "base prompt for 123" in prompt
    assert "6월 19일" in prompt
    assert "123" in prompt
    assert "Alice" in prompt
    assert "Al" in prompt
    assert "50" in prompt
    assert "반디의 뇌" in prompt
    assert "짧고 확실한 답을 선호한다." in prompt
    assert "기본 페르소나, 호감도 단계, 최근 대화보다 우선" in prompt
    assert "2026-05-16 12:00:00" in prompt
    assert "yesterday" in prompt
    assert "general command guide" in prompt


def test_build_system_prompt_adds_special_command_guide_for_special_user(monkeypatch):
    monkeypatch.setattr(prompts, "get_base_prompt", lambda user_id: "base prompt")
    monkeypatch.setattr(prompts, "get_current_time_text", lambda: "2026-05-16 12:00:00")

    def fake_load_text_file(path):
        if path == prompts.COMMAND_GUIDE_FILE:
            return "general command guide"
        if path == prompts.SPECIAL_COMMAND_GUIDE_FILE:
            return "special command guide"
        return "unknown guide"

    monkeypatch.setattr(prompts, "load_text_file", fake_load_text_file)

    regular_prompt = prompts.build_system_prompt(
        123,
        {"name": "Alice", "nickname": "Al", "affection": 50},
    )
    special_prompt = prompts.build_system_prompt(
        prompts.SPECIAL_USER_ID,
        {"name": "Owner", "nickname": "Owner", "affection": 1004},
    )

    assert "general command guide" in regular_prompt
    assert "special command guide" not in regular_prompt
    assert "general command guide" in special_prompt
    assert "special command guide" in special_prompt


def test_build_system_prompt_can_disable_command_guides(monkeypatch):
    monkeypatch.setattr(prompts, "get_base_prompt", lambda user_id: "base prompt")
    monkeypatch.setattr(prompts, "load_text_file", lambda path: "/검색실행 {프롬프트}")
    monkeypatch.setattr(prompts, "get_current_time_text", lambda: "2026-05-16 12:00:00")

    prompt = prompts.build_system_prompt(
        prompts.SPECIAL_USER_ID,
        {"name": "Owner", "nickname": "Owner", "affection": 1004},
        include_command_guides=False,
    )

    assert "/검색실행 {프롬프트}" not in prompt
    assert "봇 명령어를 출력하지 말고" in prompt


def test_special_command_guide_describes_poll_placeholders_before_examples():
    guide = prompts.load_text_file(prompts.SPECIAL_COMMAND_GUIDE_FILE)

    poll_section_start = guide.index("[투표 명령어 형식]")
    variable_section_start = guide.index("[투표 명령어 변수]")
    example_section_start = guide.index("[투표 명령어 예시]")

    assert poll_section_start < variable_section_start < example_section_start
    assert "/투표 {제목} | 항목수={항목수} | {항목1} | {항목2}" in guide
    assert "{항목수}는 실제로 출력한 투표 항목의 개수와 반드시 같아야 한다." in guide
    assert "사용자가 \"3개 정도 골라서\"라고 하면 {항목수}=3으로 쓰고 {항목1}, {항목2}, {항목3}을 모두 채운다." in guide
    assert "반드시 `/실행 /투표 ... || {프롬프트}` 형식을 사용한다." in guide
    assert "도구 선택기 JSON으로 계획할 때는 `/실행`을 `commands`에 넣지 말고" in guide
    assert "이유, 설명, 코멘트, 타이픈으로 붙인 문장은 투표 항목에 넣지 않는다." in guide
    assert "`2주`" in guide
    assert "`1달`" in guide
    assert "총 `{항목수}+3`조각이어야 한다." in guide
    assert "형식 검증 실패 메시지" in guide
    assert "특정 기능별 예외" in guide
    assert "자동 명령 실행 기록" in guide
    assert "마감만 새 값으로 바꾼" not in guide


def test_tool_planner_prompt_unwraps_poll_explanation_intent():
    guide = prompts.load_text_file(TOOL_PLANNER_PROMPT_FILE)

    assert "JSON 계획 안에서는 `/실행`, `/명령답변` 같은 명령 어댑터를 `commands`에 넣지 않는다." in guide
    assert "투표 항목에는 후보명만 넣고 링크, 가격, 장단점, 이유는 후속 답변에서 다룬다." in guide


def test_general_command_guide_uses_placeholder_sections_for_common_commands():
    guide = prompts.load_text_file(prompts.COMMAND_GUIDE_FILE)

    format_start = guide.index("\n[일반 명령어 형식]")
    variable_start = guide.index("\n[일반 명령어 변수]")
    example_start = guide.index("\n[일반 명령어 예시]")
    attachment_start = guide.index("\n[첨부 파일 처리 규칙]")

    assert attachment_start < format_start < variable_start < example_start
    assert "/호칭 {호칭}" in guide
    assert "/프로필 {유저멘션}" in guide
    assert "/주사위 {시작숫자} {끝숫자}" in guide
    assert "/팀나누기 팀수={팀수} | {참가자목록}" in guide
    assert "/실행 {명령어} | {프롬프트}" in guide
    assert "/실행 {명령어1} && {명령어2} || {프롬프트}" in guide
    assert "/요약 {범위} {개수}" in guide
    assert "/최신소식 {동작}" in guide
    assert "/주제 목록" in guide
    assert "{범위}는 `개인` 또는 `방` 중 하나다." in guide
    assert "{개수}는 생략할 수 있는 숫자이며, 사용자가 말한 요약할 최근 메시지 수다." in guide
    assert "반디 자신의 이름이나 봇 이름 변경 요청에는 `/호칭`을 출력하지 않는다." in guide
    assert "주사위 결과로 이어서 계산하거나 판단해야 하면" in guide
    assert "뒤 명령어의 입력값이 앞 명령어 결과에 따라 달라지면" in guide
    assert "나온 숫자만큼 투표 항목 만들어줘" in guide
    assert "명령어 실행과 대화 답변을 동시에 원하면 일반 명령어를 단독 출력하지 말고 반드시 `/실행`을 사용한다." in guide
    assert "먼저 실행할 명령어가 여러 개면" in guide
    assert "첨부 파일을 요약해 달라는 말은 `/요약` 명령이 아니라 파일 내용에 대한 자연어 답변" in guide


def test_special_command_guide_uses_placeholder_sections_for_non_poll_commands():
    guide = prompts.load_text_file(prompts.SPECIAL_COMMAND_GUIDE_FILE)

    format_start = guide.index("[특별 명령어 형식]")
    variable_start = guide.index("[특별 명령어 변수]")
    poll_start = guide.index("[투표 명령어 형식]")

    assert format_start < variable_start < poll_start
    assert "/요약 {파일명}" in guide
    assert "/요약 {파일인덱스}" in guide
    assert "/녹음검색 {파일명} {질문}" in guide
    assert "/녹음검색 {파일인덱스} {질문}" in guide
    assert "/투표마감 최근" in guide
    assert "/투표마감 {메시지ID}" in guide
    assert "/메모리파일 {메모리대상}" in guide
    assert "/메모리초기화 {메모리대상} 확인" in guide
    assert "/검색실행 {프롬프트}" in guide
    assert "/검색실행 {명령어들} || {프롬프트}" in guide
    assert "/인터넷모드 {상태}" in guide
    assert "/추론 {추론단계}" in guide
    assert "/뇌추가 {유저ID} {기억후보}" in guide
    assert "/뇌수정 {유저ID} {번호} {평가}" in guide
    assert "/뇌삭제 {유저ID} {번호}" in guide
    assert "/뇌삭제 {유저ID} S{번호}" in guide
    assert "/뇌삭제 {유저ID} 단기" in guide
    assert "/호칭 {유저멘션또는ID또는기존호칭} {호칭}" in guide
    assert "/호감도설정 {유저멘션} {숫자}" in guide
    assert "/최신소식 시간 {시간}" in guide
    assert "/주제 설정 {주제목록}" in guide
    assert "{상태}는 `on` 또는 `off`만 사용한다." in guide
    assert "{추론단계}" in guide
    assert "{기억후보}" in guide
    assert "{평가}" in guide
    assert "{유저ID}" in guide
    assert "현재 메시지를 보낸 사용자를 대상으로 삼아야 하면" in guide
    assert "다른 사람의 호칭 변경 요청을 `/호칭 {호칭}`처럼 한 인자만 있는 자기 호칭 변경 명령으로 바꾸지 않는다." in guide
    assert "최종 답변 한 번에만 인터넷 검색을 사용하고 방 설정은 바꾸지 않는다." in guide
    assert "반디의 뇌를 보자고 하면 대상 사용자를 명시" in guide
    assert "그것만으로 저장하지 않는다" in guide
    assert "단기 기억 후보에 넣는다" in guide
    assert "장기 기억으로 승격한다" in guide
    assert "중요도=높음" in guide
    assert "감정=경계" in guide
    assert "거리감=거리둠" in guide
    assert "정서 방향, 신뢰/경계, 거리감" in guide
    assert "단기 기억 후보가 10개 미만이면 거의 매 대화" in guide
    assert "좋아해`, `고마워`, `보고 싶어" in guide
    assert "기존 후보와 대조" in guide
    assert "/뇌삭제 {유저ID} S{번호}" in guide
    assert "저장하지 않기로 판단했다면 별도의 안내" in guide
    assert "사소한 취향, 일회성 일정" in guide
    assert "호감도 증감은 사용자가 반복적으로 배려" in guide
    assert "후속 명령어는 `/실행`이 결과를 본 뒤 고르게 둔다." in guide
    assert "이번 질문만 검색" in guide
    assert "대화=`conversation_memory.json`" in guide
    assert "임의로 여러 파일을 초기화하지 않는다." in guide
    assert "{파일명}은 사용자가 직접 말한 파일명이나 `최근` 중 하나다." in guide
    assert "{파일인덱스}`: `/대화목록`에 표시된 통화 기록 번호다." in guide
    assert "투표 조기 마감해줘" in guide
    assert "{주제목록}은 쉼표로 구분한 주제 목록이다." in guide

