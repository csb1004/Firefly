import json

import predict_tool
import reward_function
import train_rl_tool_selector
import tool_discovery
import train_tool_selector


def test_reward_function_supports_partial_multi_tool_credit():
    assert reward_function.calculate_reward(["search", "summarize"], ["search"]) == 0.75
    assert reward_function.calculate_reward(["search"], ["search"]) == 1.0
    assert reward_function.calculate_reward(["search"], ["poll"]) == -1.0


def test_train_and_predict_tool_selector_contract(tmp_path):
    rows = [
        {
            "user_message": "투표 만들어줘",
            "actions": ["투표"],
            "split": "train",
        },
        {
            "user_message": "주사위 굴려줘",
            "actions": ["주사위"],
            "split": "train",
        },
    ]
    model = train_tool_selector.train(rows)
    model_path = tmp_path / "model.json"
    model_path.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")

    prediction = predict_tool.select_tool("투표 부탁해", model_path=model_path)

    assert prediction["selected_tools"]
    assert prediction["candidate_tools"][0]["tool"] == "투표"
    assert 0.0 <= prediction["confidence"] <= 1.0


def test_tool_discovery_finds_real_slash_commands():
    schema = tool_discovery.discover_tools()
    names = {tool["name"] for tool in schema["tools"]}

    assert "투표" in names
    assert "역할" in names
    assert "뇌추가" in names


def test_rl_tool_selector_trains_and_predicts_single_tool():
    rows = [
        {
            "user_message": "투표 실행",
            "expected_tools": ["투표"],
            "available_tools": ["투표", "주사위"],
            "task_type": "Single Tool",
        },
        {
            "user_message": "주사위 실행",
            "expected_tools": ["주사위"],
            "available_tools": ["투표", "주사위"],
            "task_type": "Single Tool",
        },
    ] * 5

    model, history = train_rl_tool_selector.train(
        rows,
        episodes=8,
        learning_rate=0.25,
        epsilon=0.0,
        seed=7,
    )
    prediction = train_rl_tool_selector.predict_with_model(
        model,
        "투표 부탁해",
        available_tools=["투표", "주사위"],
    )

    assert history
    assert prediction["selected_tools"] == ["투표"]
    assert 0.0 <= prediction["confidence"] <= 1.0


def test_rl_tool_selector_can_learn_multi_tool_action():
    rows = [
        {
            "user_message": "뇌추가 먼저 하고 투표까지 이어서 실행",
            "expected_tools": ["뇌추가", "투표"],
            "available_tools": ["뇌추가", "투표", "역할"],
            "task_type": "Multi Tool",
        },
        {
            "user_message": "역할 실행",
            "expected_tools": ["역할"],
            "available_tools": ["뇌추가", "투표", "역할"],
            "task_type": "Single Tool",
        },
    ] * 6

    model, _history = train_rl_tool_selector.train(
        rows,
        episodes=10,
        learning_rate=0.25,
        epsilon=0.0,
        seed=11,
        max_sequence_actions=10,
    )
    prediction = train_rl_tool_selector.predict_with_model(
        model,
        "뇌추가 먼저 하고 투표까지 이어서 실행",
        available_tools=["뇌추가", "투표", "역할"],
    )

    assert prediction["selected_tools"] == ["뇌추가", "투표"]
