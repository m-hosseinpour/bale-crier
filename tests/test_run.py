import json
import os
from datetime import datetime, timezone

import pytest
import requests

from bale_crier.cli import main
from bale_crier.config import Settings
from bale_crier.history import read_all
from bale_crier.memory import WatcherMemory
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


def memory(tmp_path) -> WatcherMemory:
    return WatcherMemory.load(tmp_path / "data" / "watchers.json")


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


def stub_credit(monkeypatch, body):
    monkeypatch.setattr(requests, "get", lambda *a, **kw: FakeResponse(body))


def test_build_producers_is_empty_without_smoke(tmp_path):
    assert build_producers(settings(), memory=memory(tmp_path)) == []


def test_build_producers_has_the_smoke_producer(tmp_path):
    producers = build_producers(settings(smoke=True), memory=memory(tmp_path))

    assert [producer.name for producer in producers] == ["smoke"]


def test_the_credit_watcher_is_left_out_of_the_daily_set(tmp_path):
    producers = build_producers(settings(avalai_api_key="key", smoke=True), memory=memory(tmp_path))

    assert [producer.name for producer in producers] == ["smoke"]


def test_only_credit_selects_the_watcher_alone(tmp_path):
    producers = build_producers(
        settings(avalai_api_key="key", smoke=True), memory=memory(tmp_path), only=["credit"]
    )

    assert [producer.name for producer in producers] == ["credit"]


def test_an_unknown_only_name_raises(tmp_path):
    with pytest.raises(ValueError):
        build_producers(settings(), memory=memory(tmp_path), only=["nope"])


def test_no_key_means_no_credit_watcher_even_under_only(tmp_path):
    producers = build_producers(settings(), memory=memory(tmp_path), only=["credit"])

    assert producers == []


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


def test_a_run_that_produces_nothing_leaves_no_memory_file(tmp_path):
    send, calls = stub_sender(SendResult(ok=True))

    run_once(settings(), now=NOW, send=send)

    assert calls == []
    assert not (tmp_path / "data" / "watchers.json").exists()


def test_a_run_whose_watcher_sets_the_latch_leaves_it_on_disk(tmp_path, monkeypatch):
    stub_credit(monkeypatch, {"remaining_irt": 1000, "credit_sources": {"packages": []}})
    send, calls = stub_sender(SendResult(ok=True))

    report = run_once(settings(avalai_api_key="key"), now=NOW, send=send, only=["credit"])

    assert report.sent == 1
    assert report.producers == ["credit"]
    blob = json.loads((tmp_path / "data" / "watchers.json").read_text(encoding="utf-8"))
    assert blob["credit"]["armed"] is False


def test_a_credit_alert_is_recorded_in_the_history(tmp_path, monkeypatch):
    """The alert is what the owner read, so it belongs in the history like any other
    bulletin — not only in the watcher's own memory."""
    stub_credit(monkeypatch, {"remaining_irt": 1000, "credit_sources": {"packages": []}})
    send, _ = stub_sender(SendResult(ok=True))

    run_once(settings(avalai_api_key="key"), now=NOW, send=send, only=["credit"])

    records = read_all(path=tmp_path / "data" / "history.jsonl")
    assert len(records) == 1
    assert records[0].kind == "alert"
    assert records[0].ok is True
    assert records[0].note_id is None


def test_the_credit_watcher_says_nothing_when_the_balance_is_above_the_threshold(
    tmp_path, monkeypatch
):
    stub_credit(monkeypatch, {"remaining_irt": 500_000, "credit_sources": {"packages": []}})
    send, calls = stub_sender(SendResult(ok=True))

    report = run_once(settings(avalai_api_key="key"), now=NOW, send=send, only=["credit"])

    assert calls == []
    assert report.sent == 0
    # Nothing was written, so no latch file either.
    assert not (tmp_path / "data" / "watchers.json").exists()


def test_only_credit_without_a_key_reports_it_in_persian(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CRIER_BALE_BOT_TOKEN", "token")
    monkeypatch.setenv("CRIER_BALE_CHAT_ID", "7")

    code = main(["--only", "credit"])

    captured = capsys.readouterr()
    assert code == 0
    assert "CRIER_AVALAI_API_KEY" in captured.err
    assert any("\u0600" <= char <= "\u06ff" for char in captured.err)
    # «نمی‌شود»: a half-space word written without U+200C still reads as Persian.
    assert "\u200c" in captured.err
