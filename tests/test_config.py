import pytest

from firefly import config


def test_get_int_env_uses_default_and_enforces_bounds(monkeypatch):
    monkeypatch.delenv("VOICE_TEST_INT", raising=False)

    assert config._get_int_env("VOICE_TEST_INT", 7, minimum=1, maximum=10) == 7

    monkeypatch.setenv("VOICE_TEST_INT", "0")
    with pytest.raises(ValueError, match="at least 1"):
        config._get_int_env("VOICE_TEST_INT", 7, minimum=1, maximum=10)

    monkeypatch.setenv("VOICE_TEST_INT", "11")
    with pytest.raises(ValueError, match="at most 10"):
        config._get_int_env("VOICE_TEST_INT", 7, minimum=1, maximum=10)


def test_get_float_env_rejects_invalid_values(monkeypatch):
    monkeypatch.setenv("VOICE_TEST_FLOAT", "not-a-number")

    with pytest.raises(ValueError, match="must be a number"):
        config._get_float_env("VOICE_TEST_FLOAT", 1.5)
