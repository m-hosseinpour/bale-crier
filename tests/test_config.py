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


def test_defaults_are_the_ones_the_spec_settles(monkeypatch):
    monkeypatch.setenv("CRIER_BALE_BOT_TOKEN", "token")
    monkeypatch.setenv("CRIER_BALE_CHAT_ID", "123")

    settings = load_settings()

    assert settings.lists_dir == Path("lists")
    assert settings.history_path == Path("data/history.jsonl")
    assert settings.history_max_lines == 5000
    assert settings.note_floor_days == 30
    assert settings.http_timeout == 30
    assert settings.smoke is False
    assert settings.open_ai_base_url == "https://api.avalai.ir/v1"
    assert settings.open_ai_model == "deepseek-v4-flash"
    assert settings.open_ai_api_key is None
    assert settings.avalai_api_key is None


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
