import os
from datetime import datetime, timezone

import pytest
import requests

from bale_crier.cli import main
from bale_crier.config import Settings
from bale_crier.history import read_all
from bale_crier.models import SendResult
from bale_crier.run import build_producers, run_once

NOW = datetime(2026, 10, 17, 8, 30, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Run in an empty directory: the developer's own .env must not reach the tests."""
    monkeypatch.chdir(tmp_path)
    for name in list(os.environ):
        if name.startswith("CRIER_"):
            monkeypatch.delenv(name)


def settings(**overrides) -> Settings:
    fields = {
        "bale_bot_token": "token",
        "bale_chat_id": 7,
        "history_path": "data/history.jsonl",
    }
    fields.update(overrides)
    return Settings(**fields)


def stub_sender(result: SendResult):
    calls = []

    def send(text, **kwargs):
        calls.append({"text": text, **kwargs})
        return result

    return send, calls


class FakeResponse:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def test_build_producers_is_empty_without_smoke():
    assert build_producers(settings()) == []


def test_build_producers_has_the_smoke_producer():
    producers = build_producers(settings(smoke=True))

    assert [producer.name for producer in producers] == ["smoke"]


def test_without_smoke_nothing_is_sent_and_no_history_is_written(tmp_path):
    send, calls = stub_sender(SendResult(ok=True))

    report = run_once(settings(), now=NOW, send=send)

    assert calls == []
    assert not (tmp_path / "data" / "history.jsonl").exists()
    assert report.sent == 0
    assert report.failed == 0
    assert report.producers == []


def test_a_successful_smoke_run_sends_once_and_records_it(tmp_path):
    send, calls = stub_sender(SendResult(ok=True))

    report = run_once(settings(smoke=True), now=NOW, send=send)

    assert len(calls) == 1
    assert calls[0]["token"] == "token"
    assert calls[0]["chat_id"] == 7
    records = read_all(path=tmp_path / "data" / "history.jsonl")
    assert len(records) == 1
    assert records[0].ok is True
    assert records[0].kind == "smoke"
    assert records[0].text == calls[0]["text"]
    assert report.sent == 1
    assert report.failed == 0
    assert report.producers == ["smoke"]


def test_a_failed_send_is_still_recorded(tmp_path):
    send, _ = stub_sender(SendResult(ok=False, error="chat not found"))

    report = run_once(settings(smoke=True), now=NOW, send=send)

    records = read_all(path=tmp_path / "data" / "history.jsonl")
    assert len(records) == 1
    assert records[0].ok is False
    assert report.sent == 0
    assert report.failed == 1


def test_main_returns_zero_when_the_send_lands(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CRIER_BALE_BOT_TOKEN", "token")
    monkeypatch.setenv("CRIER_BALE_CHAT_ID", "7")
    monkeypatch.setenv("CRIER_SMOKE", "1")
    monkeypatch.setattr(requests, "post", lambda *a, **kw: FakeResponse({"ok": True}))

    code = main([])

    assert code == 0
    summary = capsys.readouterr().out
    assert any("\u0600" <= char <= "\u06ff" for char in summary)
    # «تولیدکننده‌ها» — a half-space word written without U+200C still reads as
    # Persian, so only an explicit check notices the character going missing.
    assert "\u200c" in summary
    records = read_all(path=tmp_path / "data" / "history.jsonl")
    assert [record.ok for record in records] == [True]


def test_main_returns_non_zero_when_the_send_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("CRIER_BALE_BOT_TOKEN", "token")
    monkeypatch.setenv("CRIER_BALE_CHAT_ID", "7")
    monkeypatch.setenv("CRIER_SMOKE", "1")
    monkeypatch.setattr(
        requests,
        "post",
        lambda *a, **kw: FakeResponse({"ok": False, "description": "chat not found"}),
    )

    code = main([])

    assert code != 0
    records = read_all(path=tmp_path / "data" / "history.jsonl")
    assert [record.ok for record in records] == [False]


def test_main_reports_a_misconfiguration_as_persian_prose(capsys):
    code = main([])

    captured = capsys.readouterr()
    assert code != 0
    assert "CRIER_BALE_BOT_TOKEN" in captured.err
    assert any("\u0600" <= char <= "\u06ff" for char in captured.err)
    assert "Traceback" not in captured.err


def test_main_help_returns_zero(capsys):
    code = main(["--help"])

    assert code == 0
    assert "usage" in capsys.readouterr().out
