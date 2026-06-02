# MyWife Firefly Bot

Python Discord bot for character chat, local memory, room context, polls, daily news delivery, and voice recording summaries.

The most important runtime assets are the prompt files and memory files. Treat them as behavior-defining data, not disposable cache.

## Setup

1. Install Python dependencies:

```powershell
python -m pip install -r requirements.txt
```

2. Create a local `.env` from `.env.example` and fill in real secrets.

3. Run the bot:

```powershell
python Firefly.py
```

## Environment Variables

Required:

- `DISCORD_BOT_TOKEN`: Discord bot token.
- `OPENAI_API_KEY`: OpenAI API key.

Optional:

- `DATA_DIR`: Runtime data directory. Defaults to `/data` when present, otherwise `data/`.
- `MEMORY_FILE`: Legacy memory JSON path and base location for split memory files. Defaults to `DATA_DIR/memory.json`.
- `DEFAULT_PROMPT_FILE`: Default character prompt path. Defaults to `prompt.txt`.
- `SPECIAL_PROMPT_FILE`: Special-user prompt path. Defaults to `prompt_special.txt`.
- `NEWS_PROMPT_FILE`: Daily news prompt path. Defaults to `prompt_news.txt`.
- `VOICE_TRANSCRIPTION_MODEL`
- `VOICE_FALLBACK_TRANSCRIPTION_MODEL`
- `VOICE_REALTIME_TRANSCRIPTION_URL`
- `VOICE_SUMMARY_MODEL`
- `VOICE_SUMMARY_FALLBACK_MODEL`
- `VOICE_TRANSCRIPT_LANGUAGE`
- `VOICE_RECORDING_RETENTION_DAYS`
- `VOICE_SUMMARY_CHUNK_CHARS`
- `VOICE_TRANSCRIBER_QUEUE_SIZE`
- `VOICE_TRANSCRIPTION_COMMIT_SECONDS`
- `VOICE_TRANSCRIPTION_IDLE_COMMIT_SECONDS`
- `VOICE_TRANSCRIPTION_MIN_COMMIT_MS`
- `VOICE_FALLBACK_SESSION_MAX_SECONDS`

## Data And Prompts

- `prompt.txt`, `prompt_special.txt`, and `prompt_news.txt` define bot behavior and should be reviewed carefully before changing.
- Runtime memory is split by concern and stored next to `MEMORY_FILE`: `conversation_memory.json`, `room_memory.json`, `poll_memory.json`, and `news_memory.json`. Existing legacy `memory.json` data is still read as a fallback until split files exist.
- `memory.json`, split memory files, and `data/` are local runtime state and are ignored by git.
- Voice recordings are stored under `data/voice_records/` by default.
- The `/메모리파일 [대화/방/투표/뉴스]` command can send one split memory file or a saved voice transcript file to the special user.

## Added Commands

- `/기록검색 [파일명] 질문`: special-user-only search over saved voice transcripts. If the filename is omitted, the bot searches recent recordings.
- `/봇상태`: special-user-only runtime status for memory, rooms, polls, news, and voice recordings.
- `/프로필 [@유저]`: show a user's profile avatar, name, nickname, affection, and last-seen time.
- `/주사위 [시작] [끝]`: roll one number inside the inclusive range, e.g. `/주사위 1 6`.
- `/팀나누기 팀수=2 | Alice, Bob, Carol, Dana`: shuffle members into balanced teams. Use `팀당=3` to split by team size.
- `/실행 [명령어들] | [프롬프트]`: run bot commands first, print their results, then answer with those results as context. Separate independent commands with `&&`; if a later command depends on an earlier result, `/실행` queues the next command after seeing that result. Use `||` as the prompt separator when any command contains `|`.
- `/검색실행 [프롬프트]` or `/검색실행 [명령어들] || [프롬프트]`: special-user-only one-shot web search for the final reply without changing the room's persistent internet mode.
- `/투표마감 [메시지ID/최근]`: special-user-only early close for a poll by message ID, replied poll, latest poll, or the only active poll in the current channel.
- `/역할 ...`: special-user-only Discord role management for assigning/removing roles, changing role colors/names, and adding/removing selected role permissions.
- `/호칭 @유저 새호칭` or `/호칭 기존호칭 새호칭`: special users can change another user's nickname by mention, Discord ID, or a unique stored nickname.
- `/메모리초기화 [대화/방/투표/뉴스] 확인`: special-user-only targeted reset for one split memory file.
- Voice recording commands accept list indexes such as `1번`, `#1`, or `index:1` wherever a recording filename is accepted.
- Natural phrasing is accepted for common commands such as nickname changes, dice rolls, summaries, profile/help requests, and news subscription commands.

## Deployment

`railpack.json` starts the service with:

```powershell
python Firefly.py
```

## Verification

Run syntax checks:

```powershell
python -m compileall Firefly.py firefly
```

Run tests:

```powershell
python -m pytest
```

Tests should not require real Discord or OpenAI credentials and should not write to production `data/`, `memory.json`, or split memory files.

