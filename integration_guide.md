# Tool-Use Integration Guide

## Runtime Boundary

The Discord bot still uses `firefly.commands.handle_mentioned_message` as the command router. Explicit commands such as `/투표`, `/역할`, `/뇌추가`, and `/실행` continue to use the existing handlers.

Natural-language command selection no longer uses deterministic keyword routing in `commands_parser.normalize_natural_command` or free-text role color detection. Natural user text flows to the LLM command guide first. If the model emits a command line, the existing router executes that command.

## Tool Selection Path

```text
User Message
  |
  v
LLM command guide or trained selector candidate
  |
  v
Existing command router
  |
  v
Existing command handler/service
  |
  v
Tool usage log
  |
  v
Future dataset / BC / RL training
```

## Generated Research Layer

- `tool_discovery.py`: discovers real tools from `Firefly.py`, `firefly.command_registry`, and `firefly.commands`.
- `tools_schema.json`: schema generated from discovered tools.
- `generate_dataset.py`: schema-grounded synthetic dataset generator.
- `train_tool_selector.py`: lightweight behavior-cloning ranker.
- `predict_tool.py`: `select_tool(user_message, context=None)` prediction API.
- `evaluate_tool_policy.py`: benchmark metrics and `evaluation_report.md` writer.
- `reward_function.py`: exact and partial multi-tool reward.
- `mini_tool_env.py`: Gymnasium-style executable tool environment.
- `generate_env_tasks.py`: environment task generator.
- `train_rl_tool_selector.py`: standard-library contextual-bandit Q-learning trainer for reward-based tool selection.
- `tool_usage_logger.py`: real Discord tool usage JSONL logger.
- `convert_logs_to_dataset.py`: converts real logs into training rows.
- `offline_rl/`: extension notes for future IQL/CQL experiments.

## Current Runtime Integration

- `/실행` and model auto-command execution write usage rows to `logs/tool_usage.jsonl`.
- Runtime logs are ignored by git through `.gitignore`.
- Direct model output of `/뇌추가`, `/뇌수정`, or `/뇌삭제` is wrapped into the `/실행` adapter so the bot stores first, then answers the original request with the result as context.

## Why The Router Is Not Replaced

The existing command handlers own Discord permissions, message formatting, persistence, poll tasks, voice tasks, and role operations. The new selector layer only chooses tools; execution remains inside the existing router and service modules.

## Future Runtime Option

Once `tool_selector_model.json` is trained on enough real logs, a low-risk runtime integration point is just before `generate_reply` in `handle_mentioned_message`:

1. Call `predict_tool.select_tool(user_text, context)`.
2. Add the top candidates to the LLM prompt as non-binding hints.
3. Keep exact command execution inside `handle_mentioned_message`.
4. Log chosen tool, result, assistant response, feedback, and reward.

Do not let the selector execute tools directly. The router remains the execution boundary.
