import json
from pathlib import Path
from typing import Any

from reward_function import calculate_reward


try:
    import gymnasium as gym
    from gymnasium import spaces
except ImportError:
    class _FallbackEnv:
        metadata: dict[str, Any] = {}

    class _Discrete:
        def __init__(self, n: int):
            self.n = n

    class _SpaceNamespace:
        Discrete = _Discrete

    class _GymNamespace:
        Env = _FallbackEnv

    gym = _GymNamespace()
    spaces = _SpaceNamespace()


ROOT = Path(__file__).resolve().parent
DEFAULT_TASKS = ROOT / "env_tasks.jsonl"


def _read_tasks(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class ToolSelectionEnv(gym.Env):
    metadata = {"render_modes": ["ansi"]}

    def __init__(self, tasks_path: Path = DEFAULT_TASKS):
        self.tasks = _read_tasks(tasks_path)
        if not self.tasks:
            raise ValueError("Task file is empty.")
        self.available_tools = sorted({
            tool
            for task in self.tasks
            for tool in task.get("available_tools", [])
        })
        self.action_space = spaces.Discrete(max(1, len(self.available_tools)))
        self.observation_space = None
        self._index = 0
        self.state = self._state_for(self.tasks[0])

    def _state_for(self, task: dict[str, Any]) -> dict[str, Any]:
        return {
            "user_message": task["user_message"],
            "context": task.get("context", {}),
            "available_tools": task.get("available_tools", self.available_tools),
        }

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        if seed is not None:
            self._index = seed % len(self.tasks)
        else:
            self._index = 0
        self.state = self._state_for(self.tasks[self._index])
        return self.state, {}

    def step(self, action):
        task = self.tasks[self._index]
        predicted = self._action_to_tools(action, task)
        expected = task.get("expected_tools", task.get("actions", []))
        reward = calculate_reward(expected, predicted)
        self._index += 1
        terminated = self._index >= len(self.tasks)
        truncated = False
        info = {
            "expected_tools": expected,
            "predicted_tools": predicted,
            "task_id": task.get("id"),
        }
        if not terminated:
            self.state = self._state_for(self.tasks[self._index])
        return self.state, reward, terminated, truncated, info

    def _action_to_tools(self, action, task: dict[str, Any]) -> list[str]:
        available = task.get("available_tools") or self.available_tools
        if isinstance(action, str):
            return [action]
        if isinstance(action, (list, tuple)):
            return [str(item) for item in action]
        try:
            return [available[int(action)]]
        except (ValueError, TypeError, IndexError):
            return []

    def render(self):
        return json.dumps(self.state, ensure_ascii=False)
