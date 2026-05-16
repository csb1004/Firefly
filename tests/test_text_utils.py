from types import SimpleNamespace

from firefly.text_utils import (
    clamp_text,
    clean_discord_content,
    clean_mention,
    is_command_text,
    parse_last_int_arg,
)


def test_clean_mention_removes_bot_mention_and_compacts_spacing():
    assert clean_mention("hi <@!42>   there", 42) == "hi there"


def test_clean_discord_content_rewrites_mentions_channels_and_roles():
    message = SimpleNamespace(
        content="hi <@1> in <#2> with <@&3>",
        mentions=[SimpleNamespace(id=1, display_name="Alice")],
        channel_mentions=[SimpleNamespace(id=2, name="general")],
        role_mentions=[SimpleNamespace(id=3, name="admin")],
    )

    assert clean_discord_content(message) == "hi @Alice in #general with @admin"


def test_clean_discord_content_can_remove_bot_mention_only():
    message = SimpleNamespace(
        content="<@99> hello <@1>",
        mentions=[
            SimpleNamespace(id=99, display_name="Bot"),
            SimpleNamespace(id=1, display_name="Alice"),
        ],
        channel_mentions=[],
        role_mentions=[],
    )

    assert clean_discord_content(message, bot_user_id=99, remove_bot_mention=True) == "hello @Alice"


def test_command_detection_integer_parsing_and_clamping():
    assert is_command_text("/help")
    assert not is_command_text(" /help".replace("/", "hello"))
    assert parse_last_int_arg("set value -12") == -12
    assert parse_last_int_arg("set value nope") is None
    assert clamp_text("abcdef", 5) == "ab..."
    assert clamp_text("abc", 5) == "abc"

