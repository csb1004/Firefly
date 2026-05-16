# Codex Local Instructions

## Superpowers Compatibility

Superpowers was designed primarily around Claude Code workflows. In this
repository, use it selectively instead of treating every conversation as a
mandatory Superpowers workflow.

- Prefer Codex-native and Compound Engineering skills when they directly match
  the task, such as `ce-work`, `ce-debug`, `ce-plan`, or `ce-code-review`.
- Do not invoke `superpowers:using-superpowers` automatically for every message.
  Use a Superpowers skill only when the user's request clearly benefits from
  that specific workflow.
- If a Superpowers skill references Claude-only tools, follow the Codex tool
  mapping in this file and continue with the closest Codex-native equivalent.
- If the Codex app shows an error screen after enabling or using Superpowers,
  first retry once, then check for Codex Desktop updates. If the error repeats,
  continue without the Superpowers workflow and use the matching Compound
  Engineering skill instead.

<!-- BEGIN COMPOUND CODEX TOOL MAP -->
## Compound Codex Tool Mapping (Claude Compatibility)

This section maps Claude Code plugin tool references to Codex behavior.
Only this block is managed automatically.

Tool mapping:
- Read: use shell reads (cat/sed) or rg
- Write: create files via shell redirection or apply_patch
- Edit/MultiEdit: use apply_patch
- Bash: use shell_command
- Grep: use rg (fallback: grep)
- Glob: use rg --files or find
- LS: use ls via shell_command
- WebFetch/WebSearch: use curl or Context7 for library docs
- AskUserQuestion/Question: present choices as a numbered list in chat and wait for a reply number. For multi-select (multiSelect: true), accept comma-separated numbers. Never skip or auto-configure - always wait for the user's response before proceeding.
- Task (subagent dispatch) / Subagent / Parallel: run sequentially in main thread; use multi_tool_use.parallel for tool calls
- TaskCreate/TaskUpdate/TaskList/TaskGet/TaskStop/TaskOutput (Claude Code task-tracking, current): use update_plan (Codex's task-tracking primitive)
- TodoWrite/TodoRead (Claude Code task-tracking, legacy - deprecated, replaced by Task* tools): use update_plan
- Skill: open the referenced SKILL.md and follow it
- ExitPlanMode: ignore
<!-- END COMPOUND CODEX TOOL MAP -->
