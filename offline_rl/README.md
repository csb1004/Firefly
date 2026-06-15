# Offline RL Extension Notes

This directory is a placeholder for future tool-policy RL experiments.

Current baseline:

- `generate_dataset.py` creates schema-grounded synthetic trajectories.
- `train_tool_selector.py` trains a lightweight behavior-cloning ranker.
- `mini_tool_env.py` exposes a Gymnasium-style environment over generated tasks.
- `reward_function.py` provides exact and partial multi-tool rewards.

Extension path:

1. Use `convert_logs_to_dataset.py` to merge real Discord tool usage into training data.
2. Keep behavior cloning as the initialization policy.
3. Add IQL or CQL only behind optional dependencies so the Discord bot runtime stays stable.
4. Evaluate with `evaluate_tool_policy.py` before any runtime integration.

Non-goals for this baseline:

- PPO or RLHF implementation.
- Replacing the existing command handlers.
- Inventing tools not discovered from the repository.
