# MyWife Firefly Bot + Bandi Cards

Python Discord bot와 Discord 계정 기반 카드 뽑기 사이트가 한 저장소에 들어 있습니다. 사이트는 하루 1회(한국 시간 오전 5시 초기화) 뽑기, 천장, 컬렉션·YP 랭킹, 선물, 실시간 거래, 카드 관리 기능을 제공합니다.

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

카드 사이트를 로컬에서 실행하려면 Node.js 22+도 준비합니다.

```powershell
python -m pip install -r requirements-web.txt
Push-Location web
npm install
npm run build
Pop-Location
python -m alembic upgrade head
python -m uvicorn bandi_cards.app:app --reload --port 8000
```

Discord Developer Portal OAuth2 Redirects에는 `.env`의 `DISCORD_REDIRECT_URI`를 정확히 등록해야 합니다. 로그인한 Discord 프로필은 즉시 갱신되고, 반디봇이 이후 사용자명·표시 이름·아바타 변경을 6시간 이내 주기로 다시 동기화합니다.

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
- `TOOL_PLANNER_PROMPT_FILE`: Tool-planner-only prompt path. Defaults to `prompt_tool_planner.txt`.
- `STATE_UPDATER_PROMPT_FILE`: Internal memory/affection update prompt path. Defaults to `prompt_state_updater.txt`.
- `TOOL_PLANNER_MODEL`: Model used for command/tool planning. Defaults to `DEFAULT_MODEL`.
- `STATE_UPDATER_MODEL`: Model used for hidden brain/affection updates before persona replies. Defaults to `DEFAULT_MODEL`.
- `BANDI_TTS_URL`: Direct Bandi TTS worker URL. The bot posts `{"input": {"text": "..."}}` and expects `audio_base64` in the response or `response.output`.
- `BANDI_TTS_API_KEY`: Optional bearer token for `BANDI_TTS_URL`.
- `RUNPOD_ENDPOINT_ID` / `RUNPOD_API_KEY`: Alternative to `BANDI_TTS_URL`; calls RunPod `runsync`.
- `BANDI_TTS_TIMEOUT_SECONDS`, `BANDI_TTS_MAX_CHARS`, `BANDI_TTS_MIN_DURATION_SECONDS`, `BANDI_TTS_RETRY_ATTEMPTS`.

## Data And Prompts

- `prompt.txt`, `prompt_special.txt`, and `prompt_news.txt` define bot behavior and should be reviewed carefully before changing.
- `prompt_tool_planner.txt` is intentionally not a persona prompt. It only decides whether to return `chat`, `command`, `command_then_reply`, `clarify`, or `reject`.
- `prompt_state_updater.txt` is a separate internal state prompt. For non-command chat it may choose hidden `/뇌추가` and `/호감도증감` updates before the normal Bandi persona replies.
- Brain memory is stored as a keyword score dictionary under `brain_keywords`. Similar keywords are merged, existing scores receive a discount before updates, and legacy brain/short-term/long-term memory fields are migrated into keyword scores on load.
- Runtime memory is split by concern and stored next to `MEMORY_FILE`: `conversation_memory.json`, `room_memory.json`, `poll_memory.json`, and `news_memory.json`. Existing legacy `memory.json` data is still read as a fallback until split files exist.
- `memory.json`, split memory files, and `data/` are local runtime state and are ignored by git.
- The `/메모리파일 [대화/방/투표/뉴스]` command can send one split memory file to the special user.

## Added Commands

- `/봇상태`: special-user-only runtime status for memory, rooms, polls, and news.
- `/음성생성 [할 말]`: special-user-only Bandi voice generation. Sends the generated WAV back to Discord.
- `/프로필 [@유저]`: show a user's profile avatar, name, nickname, affection, and last-seen time.
- `/주사위 [시작] [끝]`: roll one number inside the inclusive range, e.g. `/주사위 1 6`.
- `/팀나누기 팀수=2 | Alice, Bob, Carol, Dana`: shuffle members into teams. Use `팀당=3` to split by team size, `팀별=3,6` to set each team's size explicitly, or `팀별=tagger:3,hiders:6` to name those teams.
- `/실행 [명령어들] | [프롬프트]`: run bot commands first, print their results, then answer with those results as context. Separate independent commands with `&&`; if a later command depends on an earlier result, `/실행` queues the next command after seeing that result. Use `||` as the prompt separator when any command contains `|`.
- `/검색실행 [프롬프트]` or `/검색실행 [명령어들] || [프롬프트]`: special-user-only one-shot web search for the final reply without changing the room's persistent internet mode.
- `/투표마감 [메시지ID/최근]`: special-user-only early close for a poll by message ID, replied poll, latest poll, or the only active poll in the current channel.
- `/역할 ...`: special-user-only Discord role management for assigning/removing roles, changing role colors/names, and adding/removing selected role permissions.
- `/호칭 @유저 새호칭` or `/호칭 기존호칭 새호칭`: special users can change another user's nickname by mention, Discord ID, or a unique stored nickname.
- `/메모리초기화 [대화/방/투표/뉴스] 확인`: special-user-only targeted reset for one split memory file.
- `/메모리초기화 [대화/방/투표/뉴스]`: asks for a short follow-up confirmation. Reply `확인` to execute or `취소` to abort.
- Natural messages are first checked by the tool planner instead of local keyword routing. If it selects `command`, commands run directly; if it selects `command_then_reply`, command results are fed into Bandi's reply; if it selects `chat`, hidden brain/affection updates run first and then the normal Bandi persona answers with command output disabled for that turn. Hidden state updates are only accepted for the current speaker and are validated before any special-user command path runs.

## Deployment

`railpack.json` starts the service with:

```powershell
python Firefly.py
```

카드 사이트도 별도 저장소에 올릴 필요가 없습니다. 기존 반디봇 서비스는 계속 이 저장소의 `master`를 자동 배포하고, 같은 Railway 프로젝트에 이 저장소를 소스로 쓰는 웹 서비스 하나와 PostgreSQL만 추가합니다.

- 웹 서비스: `RAILWAY_DOCKERFILE_PATH=Dockerfile.web`, healthcheck `/api/health`, replica 1개
- 반디봇 서비스: 기존 설정과 `railpack.json`의 `python Firefly.py` 시작 명령 유지

웹 이미지는 시작할 때 Alembic 마이그레이션을 적용한 뒤 FastAPI를 실행합니다. 두 서비스에는 같은 PostgreSQL `DATABASE_URL`, `CARD_SITE_URL`, `SPECIAL_USER_ID`를 넣습니다. 웹에는 Discord OAuth와 S3 환경 변수도 넣고, 봇에는 기존 `DISCORD_BOT_TOKEN`을 유지합니다. 자세한 절차와 장애 대응은 [운영 가이드](docs/operations/bandi-card-site.md)를 참고하세요.

## Verification

Run syntax checks:

```powershell
python -m compileall Firefly.py firefly tool_use_rl
```

Run tests:

```powershell
python -m pytest
```

Tests should not require real Discord or OpenAI credentials and should not write to production `data/`, `memory.json`, or split memory files.

## Tool-Use RL

Tool-use discovery, datasets, behavior-cloning baseline, and reward-based RL training live under `tool_use_rl/`.

Regenerate and train the current artifacts:

```powershell
python -m tool_use_rl.tool_discovery
python -m tool_use_rl.generate_dataset --samples 5000 --seed 42
python -m tool_use_rl.train_tool_selector --dataset tool_use_rl/synthetic_tool_dataset.jsonl
python -m tool_use_rl.generate_env_tasks --tasks 5000 --seed 42
python -m tool_use_rl.train_rl_tool_selector --tasks tool_use_rl/env_tasks.jsonl --episodes 30 --learning-rate 0.18 --epsilon 0.25 --epsilon-decay 0.97 --seed 42 --max-sequence-actions 50 --negative-samples 16 --evaluation-interval 10
python -m tool_use_rl.evaluate_tool_policy --dataset tool_use_rl/synthetic_tool_dataset.jsonl --model tool_use_rl/tool_selector_model.json
```

For a longer RL run, use:

```powershell
python -m tool_use_rl.train_rl_tool_selector --tasks tool_use_rl/env_tasks.jsonl --episodes 200 --learning-rate 0.15 --epsilon 0.35 --epsilon-decay 0.985 --seed 42 --max-sequence-actions 200 --negative-samples 32 --evaluation-interval 20
```

