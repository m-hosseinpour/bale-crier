import json
import os
import shutil
from datetime import datetime, timezone

import pytest

from bale_crier.config import Settings
from bale_crier.history import read_all as read_history
from bale_crier.models import RunRecord, SendResult
from bale_crier.run import run_once
from bale_crier.runs import append, read_all

NOW = datetime(2026, 11, 10, 2, 5, 12, 123456, tzinfo=timezone.utc)


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
        "runs_path": "data/runs.jsonl",
    }
    fields.update(overrides)
    return Settings(**fields)


def record(**overrides) -> RunRecord:
    fields = {
        "ts": NOW,
        "only": None,
        "producers": ["note"],
        "sent": 1,
        "failed": 0,
        "errors": [],
    }
    fields.update(overrides)
    return RunRecord(**fields)


def stub_sender(result: SendResult):
    calls = []

    def send(text, **kwargs):
        calls.append({"text": text, **kwargs})
        return result

    return send, calls


def test_append_creates_the_directory_and_the_file(tmp_path):
    path = tmp_path / "data" / "runs.jsonl"

    append(record(), path=path, max_lines=1000)

    assert path.is_file()


def test_two_appends_leave_two_parseable_lines(tmp_path):
    path = tmp_path / "runs.jsonl"

    append(record(sent=1), path=path, max_lines=1000)
    append(record(sent=0, producers=[]), path=path, max_lines=1000)

    lines = path.read_text(encoding="utf-8").splitlines()

    assert [json.loads(line)["sent"] for line in lines] == [1, 0]


def test_the_line_has_exactly_the_agreed_shape(tmp_path):
    path = tmp_path / "runs.jsonl"

    append(record(), path=path, max_lines=1000)

    line = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert set(line) == {"ts", "only", "producers", "sent", "failed", "errors"}
    assert line["ts"] == "2026-11-10T02:05:12.123456Z"


def test_read_all_on_a_missing_path_is_empty(tmp_path):
    assert read_all(path=tmp_path / "absent.jsonl") == []


def test_a_broken_line_is_skipped_and_the_records_after_it_survive(tmp_path):
    path = tmp_path / "runs.jsonl"
    append(record(sent=1), path=path, max_lines=1000)
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"ts": "2026-11-10T02:05:12Z", "only":')
    append(record(sent=2), path=path, max_lines=1000)

    records = read_all(path=path)

    assert [item.sent for item in records] == [1, 2]


def test_the_cap_keeps_the_newest_lines_in_order(tmp_path):
    path = tmp_path / "runs.jsonl"

    for index in range(4):
        append(record(sent=index), path=path, max_lines=3)

    assert [item.sent for item in read_all(path=path)] == [1, 2, 3]
    # The trim goes through a neighbour file and a rename; it must not leave the
    # neighbour behind.
    assert list(path.parent.glob("*.tmp")) == []


def test_a_cap_below_one_is_refused_before_anything_is_written(tmp_path):
    path = tmp_path / "runs.jsonl"
    append(record(), path=path, max_lines=1000)

    with pytest.raises(ValueError):
        append(record(), path=path, max_lines=0)

    assert len(read_all(path=path)) == 1


def test_a_quiet_run_still_records_a_line(tmp_path):
    """No producer is built, so nothing could be sent — and the log must say the run
    happened anyway."""
    send, calls = stub_sender(SendResult(ok=True))

    run_once(settings(), now=NOW, send=send)

    assert calls == []
    records = read_all(path=tmp_path / "data" / "runs.jsonl")
    assert len(records) == 1
    assert records[0].ts == NOW
    assert records[0].only is None
    assert records[0].producers == []
    assert records[0].sent == 0
    assert records[0].failed == 0
    assert records[0].errors == []


def test_the_ordinary_run_records_only_as_null(tmp_path):
    send, _ = stub_sender(SendResult(ok=True))

    run_once(settings(smoke=True), now=NOW, send=send)

    records = read_all(path=tmp_path / "data" / "runs.jsonl")

    assert records[0].only is None
    assert records[0].producers == ["smoke"]


def test_an_only_run_records_its_names_as_a_list(tmp_path):
    send, _ = stub_sender(SendResult(ok=True))

    run_once(settings(smoke=True), now=NOW, send=send, only=["smoke"])

    records = read_all(path=tmp_path / "data" / "runs.jsonl")
    assert records[0].only == ["smoke"]
    assert records[0].producers == ["smoke"]
    assert records[0].sent == 1


def test_a_failed_send_records_the_failure_and_the_senders_reason(tmp_path):
    send, _ = stub_sender(SendResult(ok=False, error="message is too long"))

    run_once(settings(smoke=True), now=NOW, send=send, only=["smoke"])

    records = read_all(path=tmp_path / "data" / "runs.jsonl")
    assert records[0].sent == 0
    assert records[0].failed == 1
    assert records[0].errors == ["message is too long"]


def test_a_built_producer_that_produces_nothing_still_records_a_line(tmp_path, monkeypatch):
    """A quiet run is not the same as a run that built nothing: the disk watcher
    above its threshold ran, and the log must say it was there."""
    class Usage:
        free = 10 * 1024**3
        total = 100 * 1024**3
        used = 90 * 1024**3

    monkeypatch.setattr(shutil, "disk_usage", lambda path: Usage())
    send, calls = stub_sender(SendResult(ok=True))

    run_once(settings(), now=NOW, send=send, only=["disk"])

    assert calls == []
    records = read_all(path=tmp_path / "data" / "runs.jsonl")
    assert records[0].only == ["disk"]
    assert records[0].producers == ["disk"]
    assert records[0].sent == 0
    assert records[0].failed == 0
    assert records[0].errors == []


def test_a_run_with_no_producer_still_records_a_line(tmp_path):
    """`--only credit` without a key builds nothing; the scope ran, and the log must
    let the dashboard say so rather than showing a timer that never fired."""
    send, calls = stub_sender(SendResult(ok=True))

    run_once(settings(), now=NOW, send=send, only=["credit"])

    assert calls == []
    records = read_all(path=tmp_path / "data" / "runs.jsonl")
    assert len(records) == 1
    assert records[0].only == ["credit"]
    assert records[0].producers == []


def test_the_history_stays_free_of_run_records(tmp_path):
    send, _ = stub_sender(SendResult(ok=True))

    run_once(settings(smoke=True), now=NOW, send=send, only=["smoke"])

    history_lines = (
        (tmp_path / "data" / "history.jsonl").read_text(encoding="utf-8").splitlines()
    )
    assert len(history_lines) == 1
    stored = json.loads(history_lines[0])
    assert stored["kind"] == "smoke"
    assert "only" not in stored
    assert "producers" not in stored
    assert len(read_history(path=tmp_path / "data" / "history.jsonl")) == 1


def test_a_run_that_raises_writes_no_line(tmp_path, monkeypatch):
    """A crash is a stale pulse, not a quiet run: the line goes only after the run
    has finished its work."""

    def broken(settings, *, memory, only=None):
        raise RuntimeError("boom")

    monkeypatch.setattr("bale_crier.run.build_producers", broken)

    with pytest.raises(RuntimeError):
        run_once(settings(), now=NOW, send=stub_sender(SendResult(ok=True))[0])

    assert not (tmp_path / "data" / "runs.jsonl").exists()
