# Tool-Use Integration Guide

## Runtime Boundary

The Discord bot still uses `firefly.commands.handle_mentioned_message` as the command router. Explicit commands such as `/투표`, `/역할`, `/뇌추가`, and `/실행` continue to use the existing handlers.

Natural-language command selection should not depend on broad keyword routing for tool choice. Natural user text flows to the LLM command guide first where possible. If the model emits a command line, the existing router executes that command. Explicit `/역할` still uses the role handler; free-text role color detection is guarded so poll requests with color words such as `화이트` are not routed to role management.

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

All research-layer files live under `tool_use_rl/`.

- `tool_use_rl/tool_discovery.py`: discovers real tools from `Firefly.py`, `firefly.command_registry`, and `firefly.commands`.
- `tool_use_rl/tools_schema.json`: schema generated from discovered tools.
- `tool_use_rl/generate_dataset.py`: schema-grounded synthetic dataset generator.
- `tool_use_rl/train_tool_selector.py`: lightweight behavior-cloning ranker.
- `tool_use_rl/predict_tool.py`: `select_tool(user_message, context=None)` prediction API.
- `tool_use_rl/evaluate_tool_policy.py`: benchmark metrics and `evaluation_report.md` writer.
- `tool_use_rl/reward_function.py`: exact and partial multi-tool reward.
- `tool_use_rl/mini_tool_env.py`: Gymnasium-style executable tool environment.
- `tool_use_rl/generate_env_tasks.py`: environment task generator.
- `tool_use_rl/train_rl_tool_selector.py`: standard-library contextual-bandit Q-learning trainer for reward-based tool selection.
- `tool_use_rl/tool_usage_logger.py`: real Discord tool usage JSONL logger.
- `tool_use_rl/convert_logs_to_dataset.py`: converts real logs into training rows.
- `tool_use_rl/offline_rl/`: extension notes for future IQL/CQL experiments.

## Training Commands

```powershell
python -m tool_use_rl.tool_discovery
python -m tool_use_rl.generate_dataset --samples 5000 --seed 42
python -m tool_use_rl.train_tool_selector --dataset tool_use_rl/synthetic_tool_dataset.jsonl
python -m tool_use_rl.generate_env_tasks --tasks 5000 --seed 42
python -m tool_use_rl.train_rl_tool_selector --tasks tool_use_rl/env_tasks.jsonl --episodes 30 --learning-rate 0.18 --epsilon 0.25 --epsilon-decay 0.97 --seed 42 --max-sequence-actions 50 --negative-samples 16 --evaluation-interval 10
python -m tool_use_rl.evaluate_tool_policy --dataset tool_use_rl/synthetic_tool_dataset.jsonl --model tool_use_rl/tool_selector_model.json
```

Longer local RL run:

```powershell
python -m tool_use_rl.train_rl_tool_selector --tasks tool_use_rl/env_tasks.jsonl --episodes 200 --learning-rate 0.15 --epsilon 0.35 --epsilon-decay 0.985 --seed 42 --max-sequence-actions 200 --negative-samples 32 --evaluation-interval 20
```

## Current Runtime Integration

- `/실행` and model auto-command execution write usage rows to `logs/tool_usage.jsonl`.
- Runtime logs are ignored by git through `.gitignore`.
- Direct model output of `/뇌추가`, `/뇌수정`, or `/뇌삭제` is wrapped into the `/실행` adapter so the bot stores first, then answers the original request with the result as context.

## Why The Router Is Not Replaced

The existing command handlers own Discord permissions, message formatting, persistence, poll tasks, and role operations. The new selector layer only chooses tools; execution remains inside the existing router and service modules.

## Future Runtime Option

Once `tool_use_rl/tool_selector_model.json` is trained on enough real logs, a low-risk runtime integration point is just before `generate_reply` in `handle_mentioned_message`:

1. Call `tool_use_rl.predict_tool.select_tool(user_text, context)`.
2. Add the top candidates to the LLM prompt as non-binding hints.
3. Keep exact command execution inside `handle_mentioned_message`.
4. Log chosen tool, result, assistant response, feedback, and reward.

Do not let the selector execute tools directly. The router remains the execution boundary.
