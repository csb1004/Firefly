from firefly.embeds import create_help_embed, create_special_help_embed


def _field_text(embed):
    return "\n".join(f"{field.name}\n{field.value}" for field in embed.fields)


def test_special_help_lists_admin_status_commands():
    text = _field_text(create_special_help_embed())

    assert "/봇상태" in text
    assert "/관리상태" in text


def test_special_help_keeps_poll_help_short():
    text = _field_text(create_special_help_embed())

    assert "`10분`" in text
    assert "`2시간`" in text
    assert "`2주`" in text
    assert "`23:30`" in text
    assert "ISO" not in text


def test_help_lists_profile_dice_team_and_adapter_commands():
    text = _field_text(create_help_embed())

    assert "/프로필 [@유저]" in text
    assert "/주사위 [시작] [끝]" in text
    assert "/팀나누기" in text
    assert "/실행 [명령어들] | [프롬프트]" in text
    assert "관리 권한이 필요한 명령은 여기서도 권한을 우회할 수 없어" in text
    assert "텍스트 파일 첨부" in text
    assert "md" in text


def test_special_help_lists_one_shot_web_search_command():
    text = _field_text(create_special_help_embed())

    assert "/검색실행 [프롬프트]" in text
    assert "/검색실행 [명령어들] || [프롬프트]" in text


def test_special_help_lists_split_memory_commands():
    text = _field_text(create_special_help_embed())

    assert "/메모리파일 [대화/방/투표/뉴스]" in text
    assert "/메모리초기화 [대상] 확인" in text


def test_special_help_lists_role_management_commands():
    text = _field_text(create_special_help_embed())

    assert "/역할 부여 @유저 @역할" in text
    assert "/역할 권한제거 @역할 [권한]" in text


def test_special_help_lists_reasoning_and_brain_commands():
    text = _field_text(create_special_help_embed())

    assert "/추론 [없음/낮음/보통/높음]" in text
    assert "/뇌추가 @유저 [키워드:점수]" in text
    assert "/뇌수정 @유저 [번호] [키워드:점수]" in text
    assert "/뇌삭제 @유저 [번호]" in text
    assert "/뇌삭제 @유저 [키워드]" in text
