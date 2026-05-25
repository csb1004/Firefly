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
- `MEMORY_FILE`: Memory JSON path. Defaults to `DATA_DIR/memory.json`.
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
- `memory.json` and `data/` are local runtime state and are ignored by git.
- Voice recordings are stored under `data/voice_records/` by default.
- The `/메모리파일` command can send the current memory file or a saved voice transcript file to the special user.

## Added Commands

- `/기록검색 [파일명] 질문`: special-user-only search over saved voice transcripts. If the filename is omitted, the bot searches recent recordings.
- `/봇상태`: special-user-only runtime status for memory, rooms, polls, news, and voice recordings.
- `/프로필 [@유저]`: show a user's profile avatar, name, nickname, affection, and last-seen time.
- `/주사위 [시작] [끝]`: roll one number inside the inclusive range, e.g. `/주사위 1 6`.
- `/팀나누기 팀수=2 | Alice, Bob, Carol, Dana`: shuffle members into balanced teams. Use `팀당=3` to split by team size.
- `/실행 [명령어] | [프롬프트]`: run a bot command first, print its result, then answer with that result as context. Use `||` as the separator when the command itself contains `|`.
- Voice recording commands accept list indexes such as `1번`, `#1`, or `index:1` wherever a recording filename is accepted.

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

Tests should not require real Discord or OpenAI credentials and should not write to production `data/` or `memory.json`.

