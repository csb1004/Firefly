from firefly.tool_planner import parse_tool_plan


def test_parse_tool_plan_rejects_chat_plan_with_commands():
    assert parse_tool_plan(
        '{"mode":"chat","commands":["/프로필"],"response":"","confidence":0.9}'
    ) is None


def test_parse_tool_plan_rejects_missing_mode_with_commands():
    assert parse_tool_plan(
        '{"commands":["/프로필"],"response":"","confidence":0.9}'
    ) is None
