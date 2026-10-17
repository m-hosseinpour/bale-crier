import os
from pathlib import Path

import pytest

from bale_crier.config import ConfigError, load_settings

PERSIAN = "\u0600-\u06FF"


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Run in an empty directory: the developer's own .env must not reach the tests."""
    monkeypatch.chdir(tmp_path)
    for name in list(os.environ):
        if name.startswith("CRIER_"):
            monkeypatch.delenv(name)


def test_chat_id_reaches_settings_as_int(monkeypatch):
    monkeypatch.setenv("CRIER_BALE_BOT_TOKEN", "token")
    monkeypatch.setenv("CRIER_BALE_CHAT_ID", "123")

    settings = load_settings()

    assert settings.bale_chat_id == 123


def test_missing_token_names_the_variable_in_persian():
    with pytest.raises(ConfigError) as caught:
        load_settings()

    message = str(caught.value)
    assert "CRIER_BALE_BOT_TOKEN" in message
    assert any("\u0600" <= char <= "\u06ff" for char in message), message


def test_invalid_chat_id_names_the_variable(monkeypatch):
    monkeypatch.setenv("CRIER_BALE_BOT_TOKEN", "token")
    monkeypatch.setenv("CRIER_BALE_CHAT_ID", "abc")

    with pytest.raises(ConfigError) as caught:
        load_settings()

    assert "CRIER_BALE_CHAT_ID" in str(caught.value)


def test_the_defaults_are_the_ones_the_spec_settles(monkeypatch):
    monkeypatch.setenv("CRIER_BALE_BOT_TOKEN", "token")
    monkeypatch.setenv("CRIER_BALE_CHAT_ID", "123")

    settings = load_settings()

    assert settings.lists_dir == Path("lists")
    assert settings.history_path == Path("data/history.jsonl")
    assert settings.history_max_lines == 5000
    assert settings.http_timeout == 30
    assert settings.smoke is False
    assert settings.open_ai_base_url == "https://api.avalai.ir/v1"
    assert settings.open_ai_model == "deepseek-v4-flash"
    assert settings.open_ai_api_key is None
    assert settings.avalai_api_key is None
    assert settings.credit_threshold_irt == 50_000
    assert settings.watchers_state_path == Path("data/watchers.json")
    assert settings.credit_unknown_alert_hours == 24


def test_dotenv_is_read(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text(
        "CRIER_BALE_BOT_TOKEN=from-dotenv\nCRIER_BALE_CHAT_ID=42\n",
        encoding="utf-8",
    )

    settings = load_settings()

    assert settings.bale_bot_token == "from-dotenv"
    assert settings.bale_chat_id == 42


def test_a_history_cap_below_one_is_refused(monkeypatch):
    monkeypatch.setenv("CRIER_BALE_BOT_TOKEN", "token")
    monkeypatch.setenv("CRIER_BALE_CHAT_ID", "123")
    monkeypatch.setenv("CRIER_HISTORY_MAX_LINES", "0")

    with pytest.raises(ConfigError) as caught:
        load_settings()

    assert "CRIER_HISTORY_MAX_LINES" in str(caught.value)


def test_the_credit_settings_take_their_values_from_the_environment(monkeypatch):
    monkeypatch.setenv("CRIER_BALE_BOT_TOKEN", "token")
    monkeypatch.setenv("CRIER_BALE_CHAT_ID", "123")
    monkeypatch.setenv("CRIER_CREDIT_THRESHOLD_IRT", "75000")
    monkeypatch.setenv("CRIER_WATCHERS_STATE_PATH", "state/watchers.json")
    monkeypatch.setenv("CRIER_CREDIT_UNKNOWN_ALERT_HOURS", "6")

    settings = load_settings()

    assert settings.credit_threshold_irt == 75000
    assert settings.watchers_state_path == Path("state/watchers.json")
    assert settings.credit_unknown_alert_hours == 6


def test_a_zero_unknown_alert_window_is_refused(monkeypatch):
    monkeypatch.setenv("CRIER_BALE_BOT_TOKEN", "token")
    monkeypatch.setenv("CRIER_BALE_CHAT_ID", "123")
    monkeypatch.setenv("CRIER_CREDIT_UNKNOWN_ALERT_HOURS", "0")

    with pytest.raises(ConfigError) as caught:
        load_settings()

    message = str(caught.value)
    assert "CRIER_CREDIT_UNKNOWN_ALERT_HOURS" in message
    assert any("\u0600" <= char <= "\u06ff" for char in message)


def test_the_llm_key_is_inherited_from_the_avalai_key(monkeypatch):
    """One key covers the credit read and the rewording, so the owner pastes it once."""
    monkeypatch.setenv("CRIER_BALE_BOT_TOKEN", "token")
    monkeypatch.setenv("CRIER_BALE_CHAT_ID", "123")
    monkeypatch.setenv("CRIER_AVALAI_API_KEY", "aa-shared")

    settings = load_settings()

    assert settings.open_ai_api_key == "aa-shared"
    assert settings.avalai_api_key == "aa-shared"


def test_an_empty_llm_key_still_inherits_the_avalai_key(monkeypatch):
    """`.env.example` ships CRIER_OPEN_AI_API_KEY empty, which must not win."""
    monkeypatch.setenv("CRIER_BALE_BOT_TOKEN", "token")
    monkeypatch.setenv("CRIER_BALE_CHAT_ID", "123")
    monkeypatch.setenv("CRIER_AVALAI_API_KEY", "aa-shared")
    monkeypatch.setenv("CRIER_OPEN_AI_API_KEY", "")

    assert load_settings().open_ai_api_key == "aa-shared"


def test_an_explicit_llm_key_wins_over_the_inherited_one(monkeypatch):
    monkeypatch.setenv("CRIER_BALE_BOT_TOKEN", "token")
    monkeypatch.setenv("CRIER_BALE_CHAT_ID", "123")
    monkeypatch.setenv("CRIER_AVALAI_API_KEY", "aa-credit")
    monkeypatch.setenv("CRIER_OPEN_AI_API_KEY", "aa-llm")

    settings = load_settings()

    assert settings.open_ai_api_key == "aa-llm"
    assert settings.avalai_api_key == "aa-credit"
