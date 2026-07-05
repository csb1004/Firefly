# Tool Discovery Report

## Project Structure
- Entry point: `Firefly.py`
- Bot initialization: `discord.Client`, `app_commands.CommandTree`, and `on_ready` in `Firefly.py`
- Slash command registration: decorators on `tree`, `news_group`, and `topic_group` in `Firefly.py`
- Text command router: `firefly.commands.handle_mentioned_message`
- Command guide prompts: `prompt_commands_general.txt` and `prompt_commands_special.txt`
- Service modules: `firefly.polls`, `firefly.brain`, `firefly.news`, `firefly.role_commands`, `firefly.storage`

## Discovery Method
- Parsed `Firefly.py` decorators for real slash commands.
- Parsed `firefly.command_registry` for registered text command aliases.
- Parsed literal `matches_command(user_text, ...)` calls in `firefly.commands` for prefix handlers.
- Kept confidence lower for regex-discovered prefix handlers because descriptions are inferred from handler location.

## Tool Type Distribution
- slash_command: 46

## Discovered Tools (46)

| Name | Type | Confidence | Source | Dependencies |
| --- | --- | ---: | --- | --- |
| memoryfile | slash_command | 1.0 | `Firefly.py:416` | firefly.storage |
| 검색실행 | slash_command | 1.0 | `Firefly.py:272` | firefly.ai |
| 관리상태 | slash_command | 1.0 | `Firefly.py:382` | firefly.polls, firefly.storage, firefly.news |
| 뇌 | slash_command | 1.0 | `Firefly.py:307` | firefly.brain, firefly.storage |
| 뇌삭제 | slash_command | 1.0 | `Firefly.py:355` | firefly.brain, firefly.storage |
| 뇌수정 | slash_command | 1.0 | `Firefly.py:337` | firefly.brain, firefly.storage |
| 뇌추가 | slash_command | 1.0 | `Firefly.py:320` | firefly.brain, firefly.storage |
| 단체모드 | slash_command | 1.0 | `Firefly.py:522` | firefly.storage |
| 도움말 | slash_command | 1.0 | `Firefly.py:167` | - |
| 메모리초기화 | slash_command | 1.0 | `Firefly.py:427` | firefly.polls, firefly.storage, firefly.news |
| 메모리파일 | slash_command | 1.0 | `Firefly.py:408` | firefly.polls, firefly.storage, firefly.news |
| 메모리파일초기화 | slash_command | 1.0 | `Firefly.py:441` | firefly.polls, firefly.storage, firefly.news |
| 방기억 | slash_command | 1.0 | `Firefly.py:527` | firefly.storage |
| 방상태 | slash_command | 1.0 | `Firefly.py:537` | - |
| 방초기화 | slash_command | 1.0 | `Firefly.py:532` | firefly.storage |
| 봇상태 | slash_command | 1.0 | `Firefly.py:377` | firefly.commands, firefly.news, firefly.polls, firefly.storage |
| 실행 | slash_command | 1.0 | `Firefly.py:257` | - |
| 역할 | slash_command | 1.0 | `Firefly.py:372` | firefly.commands, firefly.role_commands |
| 요약 | slash_command | 1.0 | `Firefly.py:392` | firefly.ai |
| 유저정보 | slash_command | 1.0 | `Firefly.py:452` | - |
| 인터넷모드 | slash_command | 1.0 | `Firefly.py:509` | firefly.ai |
| 주사위 | slash_command | 1.0 | `Firefly.py:204` | - |
| 주제 목록 | slash_command | 1.0 | `Firefly.py:614` | firefly.news |
| 주제 변경 | slash_command | 1.0 | `Firefly.py:642` | firefly.news |
| 주제 설정 | slash_command | 1.0 | `Firefly.py:635` | firefly.news |
| 주제 제거 | slash_command | 1.0 | `Firefly.py:628` | firefly.news |
| 주제 추가 | slash_command | 1.0 | `Firefly.py:621` | firefly.news |
| 초기화 | slash_command | 1.0 | `Firefly.py:177` | firefly.storage |
| 최신소식 그만 | slash_command | 1.0 | `Firefly.py:557` | firefly.news |
| 최신소식 기록초기화 | slash_command | 1.0 | `Firefly.py:602` | firefly.news |
| 최신소식 목록 | slash_command | 1.0 | `Firefly.py:573` | firefly.news |
| 최신소식 받기 | slash_command | 1.0 | `Firefly.py:544` | firefly.news |
| 최신소식 상태 | slash_command | 1.0 | `Firefly.py:568` | firefly.news |
| 최신소식 시간 | slash_command | 1.0 | `Firefly.py:580` | firefly.news |
| 최신소식 중복기록초기화 | slash_command | 1.0 | `Firefly.py:609` | firefly.news |
| 최신소식 중복삭제 | slash_command | 1.0 | `Firefly.py:595` | firefly.news |
| 최신소식 중복초기화 | slash_command | 1.0 | `Firefly.py:588` | firefly.news |
| 추론 | slash_command | 1.0 | `Firefly.py:296` | - |
| 투표 | slash_command | 1.0 | `Firefly.py:488` | firefly.polls |
| 투표마감 | slash_command | 1.0 | `Firefly.py:495` | firefly.polls |
| 팀나누기 | slash_command | 1.0 | `Firefly.py:222` | - |
| 프로필 | slash_command | 1.0 | `Firefly.py:191` | - |
| 호감도 | slash_command | 1.0 | `Firefly.py:172` | - |
| 호감도설정 | slash_command | 1.0 | `Firefly.py:464` | - |
| 호감도증감 | slash_command | 1.0 | `Firefly.py:476` | - |
| 호칭 | slash_command | 1.0 | `Firefly.py:184` | - |
