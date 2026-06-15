# Tool Discovery Report

## Project Structure
- Entry point: `Firefly.py`
- Bot initialization: `discord.Client`, `app_commands.CommandTree`, and `on_ready` in `Firefly.py`
- Slash command registration: decorators on `tree`, `news_group`, and `topic_group` in `Firefly.py`
- Text command router: `firefly.commands.handle_mentioned_message`
- Command guide prompts: `prompt_commands_general.txt` and `prompt_commands_special.txt`
- Service modules: `firefly.polls`, `firefly.brain`, `firefly.news`, `firefly.role_commands`, `firefly.voice`, `firefly.voice_search`, `firefly.storage`

## Discovery Method
- Parsed `Firefly.py` decorators for real slash commands.
- Parsed `firefly.command_registry` for registered text command aliases.
- Parsed literal `matches_command(user_text, ...)` calls in `firefly.commands` for prefix handlers.
- Kept confidence lower for regex-discovered prefix handlers because descriptions are inferred from handler location.

## Tool Type Distribution
- slash_command: 51

## Discovered Tools (51)

| Name | Type | Confidence | Source | Dependencies |
| --- | --- | ---: | --- | --- |
| memoryfile | slash_command | 1.0 | `Firefly.py:470` | firefly.storage |
| 검색실행 | slash_command | 1.0 | `Firefly.py:271` | firefly.ai |
| 관리상태 | slash_command | 1.0 | `Firefly.py:436` | firefly.polls, firefly.storage, firefly.news, firefly.voice |
| 기록 | slash_command | 1.0 | `Firefly.py:376` | firefly.voice |
| 기록검색 | slash_command | 1.0 | `Firefly.py:419` | firefly.ai, firefly.commands, firefly.voice |
| 기록중지 | slash_command | 1.0 | `Firefly.py:394` | firefly.voice |
| 녹음검색 | slash_command | 1.0 | `Firefly.py:426` | firefly.voice_search, firefly.voice, firefly.ai |
| 뇌 | slash_command | 1.0 | `Firefly.py:306` | firefly.brain, firefly.storage |
| 뇌삭제 | slash_command | 1.0 | `Firefly.py:354` | firefly.brain, firefly.storage |
| 뇌수정 | slash_command | 1.0 | `Firefly.py:336` | firefly.brain, firefly.storage |
| 뇌추가 | slash_command | 1.0 | `Firefly.py:319` | firefly.brain, firefly.storage |
| 단체모드 | slash_command | 1.0 | `Firefly.py:576` | firefly.storage |
| 대화목록 | slash_command | 1.0 | `Firefly.py:408` | firefly.voice |
| 도움말 | slash_command | 1.0 | `Firefly.py:184` | - |
| 메모리초기화 | slash_command | 1.0 | `Firefly.py:481` | firefly.polls, firefly.storage, firefly.news |
| 메모리파일 | slash_command | 1.0 | `Firefly.py:462` | firefly.polls, firefly.storage, firefly.news, firefly.voice |
| 메모리파일초기화 | slash_command | 1.0 | `Firefly.py:495` | firefly.polls, firefly.storage, firefly.news |
| 방기억 | slash_command | 1.0 | `Firefly.py:581` | firefly.storage |
| 방상태 | slash_command | 1.0 | `Firefly.py:591` | - |
| 방초기화 | slash_command | 1.0 | `Firefly.py:586` | firefly.storage |
| 봇상태 | slash_command | 1.0 | `Firefly.py:431` | firefly.commands, firefly.news, firefly.polls, firefly.storage, firefly.voice |
| 실행 | slash_command | 1.0 | `Firefly.py:256` | - |
| 역할 | slash_command | 1.0 | `Firefly.py:371` | firefly.commands, firefly.role_commands |
| 요약 | slash_command | 1.0 | `Firefly.py:446` | firefly.voice, firefly.ai |
| 유저정보 | slash_command | 1.0 | `Firefly.py:506` | - |
| 인터넷모드 | slash_command | 1.0 | `Firefly.py:563` | firefly.ai |
| 주사위 | slash_command | 1.0 | `Firefly.py:221` | - |
| 주제 목록 | slash_command | 1.0 | `Firefly.py:668` | firefly.news |
| 주제 변경 | slash_command | 1.0 | `Firefly.py:696` | firefly.news |
| 주제 설정 | slash_command | 1.0 | `Firefly.py:689` | firefly.news |
| 주제 제거 | slash_command | 1.0 | `Firefly.py:682` | firefly.news |
| 주제 추가 | slash_command | 1.0 | `Firefly.py:675` | firefly.news |
| 초기화 | slash_command | 1.0 | `Firefly.py:194` | firefly.storage |
| 최신소식 그만 | slash_command | 1.0 | `Firefly.py:611` | firefly.news |
| 최신소식 기록초기화 | slash_command | 1.0 | `Firefly.py:656` | firefly.news, firefly.voice |
| 최신소식 목록 | slash_command | 1.0 | `Firefly.py:627` | firefly.news |
| 최신소식 받기 | slash_command | 1.0 | `Firefly.py:598` | firefly.news |
| 최신소식 상태 | slash_command | 1.0 | `Firefly.py:622` | firefly.news |
| 최신소식 시간 | slash_command | 1.0 | `Firefly.py:634` | firefly.news |
| 최신소식 중복기록초기화 | slash_command | 1.0 | `Firefly.py:663` | firefly.news, firefly.voice |
| 최신소식 중복삭제 | slash_command | 1.0 | `Firefly.py:649` | firefly.news, firefly.voice |
| 최신소식 중복초기화 | slash_command | 1.0 | `Firefly.py:642` | firefly.news, firefly.voice |
| 추론 | slash_command | 1.0 | `Firefly.py:295` | - |
| 투표 | slash_command | 1.0 | `Firefly.py:542` | firefly.polls |
| 투표마감 | slash_command | 1.0 | `Firefly.py:549` | firefly.polls |
| 팀나누기 | slash_command | 1.0 | `Firefly.py:233` | - |
| 프로필 | slash_command | 1.0 | `Firefly.py:208` | - |
| 호감도 | slash_command | 1.0 | `Firefly.py:189` | - |
| 호감도설정 | slash_command | 1.0 | `Firefly.py:518` | - |
| 호감도증감 | slash_command | 1.0 | `Firefly.py:530` | - |
| 호칭 | slash_command | 1.0 | `Firefly.py:201` | - |
