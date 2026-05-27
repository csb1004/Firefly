# Project Quality Reset Design

## Purpose

This project is an existing Python Discord bot with conversation memory, character prompts, affection state, polls, daily news delivery, and voice recording/transcription/summary features. The reset should improve maintainability, stability, extensibility, and operational clarity without breaking the core character experience.

The first priority is to protect the conversation, memory, and prompt behavior. Refactoring should happen only after there is enough test coverage to detect behavior drift.

## Goals

- Preserve the current user-facing bot behavior, especially conversation, memory, affection, and prompt flow.
- Add a practical test foundation for pure logic and file-backed state.
- Document local setup, required environment variables, data paths, deployment entrypoints, and operational notes.
- Refactor large modules incrementally after tests exist.
- Follow SOLID principles when adding or changing functions, modules, and interfaces.

## Non-Goals

- Do not rewrite the bot framework or replace `discord.py`.
- Do not change the bot persona, prompt content, or memory semantics unless a test exposes a clear bug.
- Do not redesign voice recording/transcription in the first implementation phase.
- Do not introduce broad abstractions before there is repeated complexity to justify them.

## Current Shape

- `Firefly.py` is the Discord entrypoint. It owns client setup, slash commands, event handlers, and top-level routing.
- `firefly/commands.py` handles mentioned-message commands and general conversation flow.
- `firefly/storage.py` manages memory JSON state for users and rooms.
- `firefly/prompts.py` builds system prompts and model history.
- `firefly/text_utils.py` normalizes Discord message content.
- `firefly/utility_commands.py` owns pure parsing and formatting logic for utility commands such as dice, team split, and command adapters.
- `firefly/ai.py` calls OpenAI APIs for replies, summaries, voice summaries, and news digests.
- `firefly/news.py` combines news settings, command parsing, delivery scheduling, duplicate tracking, and Discord messaging.
- `firefly/voice.py` combines Discord voice receiving, PCM conversion, realtime transcription, fallback transcription, and active recording lifecycle.
- `firefly/polls.py` combines poll parsing, embeds, reaction handling, persistence, and scheduling.

`news.py` and `voice.py` are the largest modules and are good later refactoring candidates. The first phase should not start there because the user identified conversation and memory as the most important experience to protect.

## Recommended Approach

Use a behavior-preserving reset:

1. Add tests and documentation first.
2. Protect the conversation/memory/prompt path before moving code.
3. Extract only pure logic or clearly bounded responsibilities.
4. Keep Discord and OpenAI integration boundaries thin and mostly unchanged until tests exist.
5. Split large modules in later phases, one responsibility at a time.

This favors a slower visible start, but it reduces the risk of breaking the bot's personality or memory behavior.

## SOLID Guidance

Apply SOLID in a Pythonic, lightweight way:

- Single Responsibility: each new function should do one thing, such as parse a command, normalize stored state, format a response, or call an external API. Avoid functions that both mutate storage and send Discord messages unless they are explicit orchestration handlers.
- Open/Closed: add new command categories by adding isolated parser/handler units instead of expanding large conditional blocks indefinitely.
- Liskov Substitution: when using small protocol-like helpers or injected dependencies in tests, keep call signatures consistent so test doubles can replace production collaborators.
- Interface Segregation: pass only the data a function needs. Prefer small dictionaries or typed values over passing full Discord objects into pure logic.
- Dependency Inversion: keep pure logic independent from Discord, OpenAI, filesystem paths, and global config when reasonable. Orchestration code can depend on integrations; parsing and state-normalization code should not.

SOLID should not be used as a reason to create excessive class hierarchies. The default should be small functions, narrow modules, and explicit dependencies.

## Phase 1 File Plan

Add:

- `tests/test_storage.py`: tests memory loading/saving, default user data, default room data, history trimming, and room history recording.
- `tests/test_text_utils.py`: tests Discord content cleanup, mention removal, command detection, integer parsing, and text clamping.
- `tests/test_prompts.py`: tests prompt selection, group context prompt structure, and model history shaping.
- `tests/test_commands.py`: tests pure command parsing helpers such as special-only command detection and summary argument parsing.
- `README.md`: documents project purpose, local setup, environment variables, data paths, commands, deployment entrypoint, and operational notes.
- `.env.example`: documents required and optional environment variables without secrets.

Modify only as needed:

- `requirements.txt`: add `pytest` only if tests require it and the project has no existing test dependency mechanism.
- `firefly/config.py`: allow tests to import modules with controlled environment variables if current import-time checks block testing. Keep production behavior strict.
- `firefly/storage.py`, `firefly/text_utils.py`, `firefly/prompts.py`, `firefly/commands.py`: make narrow changes only when needed to expose pure logic or improve testability.

## Later Refactoring Candidates

After Phase 1 tests are passing:

- `firefly/commands_parser.py`: extract command classification and argument parsing from `commands.py`.
- `firefly/news_settings.py` or `firefly/news_state.py`: extract news settings normalization, subscriber state, topic management, and delivered-item tracking from `news.py`.
- `firefly/voice_transcription.py`: extract realtime transcription queueing, PCM conversion, commit timing, and transcript persistence coordination from `voice.py`.
- `firefly/poll_parser.py`: extract poll command parsing from `polls.py` if poll work becomes active.

These should be introduced only when a plan identifies the exact behavior to protect and the tests that prove it stayed stable.

## Command Adapter And One-Shot Search

The command adapter is a protected user-facing workflow:

- `/실행 [명령어들] | [프롬프트]` runs one or more bot commands first, then sends the collected command results into the final conversation reply as extra context.
- Multiple commands are separated with `&&` or newlines, up to a bounded maximum. This keeps a single adapter request useful without allowing runaway command chains.
- Commands that already contain `|`, such as polls or team split requests, must use `||` between the command block and the follow-up prompt.
- Adapter results are summarized and size-limited before being passed to the model so large command outputs do not dominate the prompt.
- Recursive, destructive, reset, and persistent mode-changing commands are blocked inside `/실행`.

Internet search should use the narrowest surface that satisfies the request:

- `/검색실행`, also aliased as `/인터넷실행` and `/검색답변`, is special-user-only.
- It can run optional prior commands, then forces internet search for the final answer only.
- It must not mutate the room's persistent `internet_mode` setting.
- `/인터넷모드` remains the persistent room-level mode toggle and should not be invoked through `/실행`.

## Data Flow To Protect

The core conversation path should stay conceptually unchanged:

1. `Firefly.py` receives a Discord message.
2. `text_utils.clean_discord_content()` normalizes content and removes/rewrites mentions.
3. `commands.handle_mentioned_message()` decides whether the message is a command or normal conversation.
4. Normal conversation loads user and room state through `storage.py`.
5. `prompts.py` builds system prompt and model history.
6. `ai.generate_reply()` requests the model response.
7. `storage.py` records updated user and room history.
8. Discord sends the reply.

Tests should focus on steps 2, 4, 5, and pure parsing decisions in step 3. Steps involving Discord and OpenAI should initially be smoke-tested or covered with narrow test doubles only when needed.

## Error Handling

Phase 1 should document and preserve current error behavior instead of creating a new exception framework.

Tests should verify:

- Missing memory files initialize safely.
- Invalid or partial stored user data normalizes to expected defaults.
- Invalid or partial room data normalizes to expected defaults.
- Histories are trimmed to configured limits.
- Command parsing handles missing, malformed, or extra arguments predictably.

OpenAI failures, Discord permission failures, and voice websocket failures remain later stability work unless they block testability.

## Testing Strategy

Use `pytest` for fast local tests.

Start with pure and file-backed tests:

- Pure function tests should not import or instantiate Discord clients.
- File-backed tests should use temporary paths and avoid real `data/` or `memory.json`.
- Tests should not require real Discord or OpenAI credentials.
- Import-time environment requirements should be handled through test setup or narrowly adjusted config code.

Add a smoke check:

```powershell
python -m compileall Firefly.py firefly
```

When pytest tests exist, the expected local verification command is:

```powershell
python -m pytest
```

## Documentation Strategy

`README.md` should explain:

- What the bot does.
- Required Python version and dependency installation.
- Required `.env` keys: `DISCORD_BOT_TOKEN`, `OPENAI_API_KEY`.
- Optional `.env` keys for prompt files, data directory, memory file, voice transcription settings, and recording retention.
- Data storage behavior: `data/` and `memory.json` are local/runtime state and ignored by git.
- Deployment entrypoint: `railpack.json` starts `python Firefly.py`.
- Basic verification commands.

`.env.example` should include realistic variable names but no real secrets.

## Implementation Boundaries

The first implementation plan should produce a small, reviewable change:

- Add tests and docs.
- Make minimal code adjustments required for testability.
- Avoid moving `voice.py` and `news.py` code in the first pass.
- Avoid changing prompt text unless encoding or file-loading problems must be explicitly addressed.
- Keep commits small and behavior-oriented.

## Acceptance Criteria

- Tests can run without real Discord or OpenAI credentials.
- The core conversation/memory/prompt path has initial test coverage.
- The project has basic setup and operations documentation.
- `.env.example` exists and contains no secrets.
- No broad rewrite of `Firefly.py`, `news.py`, or `voice.py` occurs in the first phase.
- New and modified functions follow the SOLID guidance above.

