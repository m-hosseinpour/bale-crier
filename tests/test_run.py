import json
import os
import shutil
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
GIB = 1024**3


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
        self.status_code = 200

    def json(self):
        return self._body


def stub_credit(monkeypatch, body):
    monkeypatch.setattr(requests, "get", lambda *a, **kw: FakeResponse(body))


def stub_llm(monkeypatch, text="متن تازهٔ امروز"):
    """The real client runs; only its HTTP call is faked, as `stub_credit` does."""
    monkeypatch.setattr(
        requests,
        "post",
        lambda *a, **kw: FakeResponse({"choices": [{"message": {"content": text}}]}),
    )


FEED_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item>
  <title>Alpha release arrives - The Outlet</title>
  <link>https://news.google.com/rss/articles/alpha</link>
  <guid isPermaLink="false">guid-alpha</guid>
  <pubDate>Sat, 17 Oct 2026 09:43:16 GMT</pubDate>
  <source url="https://the-outlet.test/">The Outlet</source>
</item>
</channel></rss>"""


def stub_disk(monkeypatch, free: int):
    class DiskUsage:
        pass

    usage = DiskUsage()
    usage.free = free
    monkeypatch.setattr(shutil, "disk_usage", lambda path: usage)


def stub_feed(monkeypatch, body: bytes = FEED_XML):
    class FeedResponse:
        status_code = 200
        content = body

    monkeypatch.setattr(requests, "get", lambda *a, **kw: FeedResponse())


def test_build_producers_is_empty_without_smoke(tmp_path):
    assert build_producers(settings(), memory=memory(tmp_path)) == []


def test_build_producers_has_the_smoke_producer(tmp_path):
    producers = build_producers(settings(smoke=True), memory=memory(tmp_path))

    assert [producer.name for producer in producers] == ["smoke"]


def test_the_credit_watcher_is_left_out_of_the_note_run(tmp_path):
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


def test_a_failed_expiry_notice_repeats_next_run_instead_of_being_lost(tmp_path, monkeypatch):
    stub_credit(
        monkeypatch,
        {
            "remaining_irt": 500_000,
            "credit_sources": {
                "packages": [
                    {
                        "template_id": "w-1",
                        "name": "وایب کُدر هفتگی پایه",
                        "remaining_irt": "300000",
                        "end_date": "2026-10-17T20:30:00Z",
                    }
                ]
            },
        },
    )
    failing, _ = stub_sender(SendResult(ok=False, error="no route"))

    run_once(settings(avalai_api_key="key"), now=NOW, send=failing, only=["credit"])

    # The memory is written only when every send landed, so the notice is not lost.
    assert not (tmp_path / "data" / "watchers.json").exists()
    assert [record.ok for record in read_all(path=tmp_path / "data" / "history.jsonl")] == [False]

    send, calls = stub_sender(SendResult(ok=True))
    run_once(settings(avalai_api_key="key"), now=NOW, send=send, only=["credit"])

    assert len(calls) == 1
    assert "منقضی" in calls[0]["text"]
    blob = json.loads((tmp_path / "data" / "watchers.json").read_text(encoding="utf-8"))
    assert blob["credit"]["expiry_announced"]

    quiet, quiet_calls = stub_sender(SendResult(ok=True))
    run_once(settings(avalai_api_key="key"), now=NOW, send=quiet, only=["credit"])

    assert quiet_calls == []


def test_the_disk_watcher_is_left_out_of_the_note_run(tmp_path):
    producers = build_producers(settings(), memory=memory(tmp_path))

    assert [producer.name for producer in producers] == []


def test_only_disk_selects_the_watcher_alone(tmp_path):
    producers = build_producers(settings(), memory=memory(tmp_path), only=["disk"])

    assert [producer.name for producer in producers] == ["disk"]


def test_the_note_run_leaves_the_disk_watcher_out(tmp_path):
    producers = build_producers(settings(open_ai_api_key="key"), memory=memory(tmp_path))

    assert [producer.name for producer in producers] == ["note"]


def test_a_disk_alert_is_recorded_in_the_history(tmp_path, monkeypatch):
    stub_disk(monkeypatch, GIB)
    send, calls = stub_sender(SendResult(ok=True))

    report = run_once(settings(), now=NOW, send=send, only=["disk"])

    assert report.sent == 1
    assert report.producers == ["disk"]
    assert len(calls) == 1
    records = read_all(path=tmp_path / "data" / "history.jsonl")
    assert len(records) == 1
    assert records[0].kind == "alert"
    assert records[0].ok is True
    blob = json.loads((tmp_path / "data" / "watchers.json").read_text(encoding="utf-8"))
    assert blob["disk"]["armed"] is False


def test_a_disk_check_with_space_to_spare_is_quiet(tmp_path, monkeypatch):
    stub_disk(monkeypatch, 10 * GIB)
    send, calls = stub_sender(SendResult(ok=True))

    report = run_once(settings(), now=NOW, send=send, only=["disk"])

    assert calls == []
    assert report.sent == 0
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


def test_build_producers_includes_the_note_producer_when_a_key_is_set(tmp_path):
    producers = build_producers(settings(open_ai_api_key="key"), memory=memory(tmp_path))

    assert [producer.name for producer in producers] == ["note"]


def test_the_note_run_leaves_the_credit_watcher_out_but_keeps_the_note(tmp_path):
    producers = build_producers(
        settings(avalai_api_key="credit-key", open_ai_api_key="llm-key"),
        memory=memory(tmp_path),
    )

    assert [producer.name for producer in producers] == ["note"]


def test_smoke_stays_alone_even_when_the_other_producers_could_run(tmp_path):
    """The deploy check is one fixed message; it must not spend a note as well."""
    producers = build_producers(
        settings(smoke=True, avalai_api_key="credit-key", open_ai_api_key="llm-key"),
        memory=memory(tmp_path),
    )

    assert [producer.name for producer in producers] == ["smoke"]


def test_only_note_selects_the_note_producer_alone(tmp_path):
    producers = build_producers(
        settings(avalai_api_key="credit-key", open_ai_api_key="llm-key"),
        memory=memory(tmp_path),
        only=["note"],
    )

    assert [producer.name for producer in producers] == ["note"]


def test_no_llm_key_means_no_note_producer_even_under_only(tmp_path):
    producers = build_producers(settings(), memory=memory(tmp_path), only=["note"])

    assert producers == []


def test_the_note_run_leaves_the_news_digest_out(tmp_path):
    producers = build_producers(settings(open_ai_api_key="llm-key"), memory=memory(tmp_path))

    names = [producer.name for producer in producers]
    assert names == ["note"]
    assert "news" not in names


def test_only_news_selects_the_digest_alone(tmp_path):
    producers = build_producers(
        settings(avalai_api_key="credit-key", open_ai_api_key="llm-key"),
        memory=memory(tmp_path),
        only=["news"],
    )

    assert [producer.name for producer in producers] == ["news"]


def test_no_llm_key_means_no_news_producer_even_under_only(tmp_path):
    producers = build_producers(settings(), memory=memory(tmp_path), only=["news"])

    assert producers == []


def test_a_news_run_sends_one_digest_and_records_what_went(tmp_path, monkeypatch):
    stub_feed(monkeypatch)
    stub_llm(monkeypatch, text="1|متن یک")
    send, calls = stub_sender(SendResult(ok=True))

    report = run_once(settings(open_ai_api_key="key"), now=NOW, send=send, only=["news"])

    assert report.sent == 1
    assert report.producers == ["news"]
    records = read_all(path=tmp_path / "data" / "history.jsonl")
    assert len(records) == 1
    assert records[0].kind == "news"
    assert records[0].ok is True
    assert records[0].note_id is None
    assert records[0].list_name is None
    assert records[0].text == calls[0]["text"]


def news_feed_xml(count: int) -> bytes:
    items = "".join(
        f"""
<item>
  <title>Headline {index} - The Outlet</title>
  <link>https://news.google.com/rss/articles/{index}</link>
  <guid isPermaLink="false">guid-{index}</guid>
  <pubDate>Sat, 17 Oct 2026 0{index}:00:00 GMT</pubDate>
  <source url="https://the-outlet.test/">The Outlet</source>
</item>"""
        for index in range(1, count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
        + items
        + "</channel></rss>"
    ).encode()


def test_a_digest_goes_out_in_groups_and_each_message_gets_its_own_record(tmp_path, monkeypatch):
    """Six stories at the default batch of five are two messages: two sends, two history
    lines. A refused second message must also keep the seen set unsaved, so the whole
    digest repeats next run rather than half of it going missing."""
    stub_feed(monkeypatch, body=news_feed_xml(6))
    stub_llm(monkeypatch, text="\n".join(f"{index}|متن {index}" for index in range(1, 7)))
    results = [SendResult(ok=True), SendResult(ok=False, error="message is too long")]
    calls = []

    def send(text, **kwargs):
        calls.append(text)
        return results[len(calls) - 1]

    report = run_once(settings(open_ai_api_key="key"), now=NOW, send=send, only=["news"])

    assert len(calls) == 2
    assert report.sent == 1
    assert report.failed == 1
    records = read_all(path=tmp_path / "data" / "history.jsonl")
    assert [record.ok for record in records] == [True, False]
    assert [record.text for record in records] == calls
    assert not (tmp_path / "data" / "watchers.json").exists()


def test_a_note_run_sends_one_note_and_records_what_went(tmp_path, monkeypatch):
    lists = tmp_path / "lists"
    lists.mkdir()
    (lists / "reading.md").write_text(
        "## reading-1\nهر روز یک صفحه کتاب بخوان\n", encoding="utf-8"
    )
    stub_llm(monkeypatch, text="هر روز، یک صفحه بخوان")
    send, calls = stub_sender(SendResult(ok=True))

    report = run_once(settings(open_ai_api_key="key", lists_dir=lists), now=NOW, send=send)

    assert report.sent == 1
    assert report.producers == ["note"]
    assert calls[0]["text"] == "هر روز، یک صفحه بخوان"
    records = read_all(path=tmp_path / "data" / "history.jsonl")
    assert len(records) == 1
    assert records[0].kind == "note"
    assert records[0].ok is True
    assert records[0].list_name == "reading"
    assert records[0].note_id == "reading-1"
    assert records[0].text == calls[0]["text"]


def test_main_says_in_persian_when_the_llm_key_is_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CRIER_BALE_BOT_TOKEN", "token")
    monkeypatch.setenv("CRIER_BALE_CHAT_ID", "7")

    code = main([])

    captured = capsys.readouterr()
    assert code == 0
    assert "CRIER_OPEN_AI_API_KEY" in captured.err
    assert any("\u0600" <= char <= "\u06ff" for char in captured.err)
    assert "\u200c" in captured.err
    assert "Traceback" not in captured.err


def test_main_says_in_persian_when_the_lists_directory_is_missing(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("CRIER_BALE_BOT_TOKEN", "token")
    monkeypatch.setenv("CRIER_BALE_CHAT_ID", "7")
    # A key, so the line about the key is not the one under test.
    monkeypatch.setenv("CRIER_AVALAI_API_KEY", "aa-key")

    code = main([])

    captured = capsys.readouterr()
    assert code == 0
    assert "lists" in captured.err
    assert "\u200c" in captured.err


def test_the_missing_lists_line_is_not_printed_for_another_producer(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("CRIER_BALE_BOT_TOKEN", "token")
    monkeypatch.setenv("CRIER_BALE_CHAT_ID", "7")
    monkeypatch.setenv("CRIER_AVALAI_API_KEY", "aa-key")
    stub_credit(monkeypatch, {"remaining_irt": 500_000, "credit_sources": {"packages": []}})

    main(["--only", "credit"])

    assert "lists" not in capsys.readouterr().err


def test_a_smoke_run_does_not_warn_about_notes_it_never_asked_for(
    monkeypatch, tmp_path, capsys
):
    """The deploy check is exactly where lists/ may not exist yet, so a warning
    about it there would be a false alarm on the flow it is meant to reassure."""
    monkeypatch.setenv("CRIER_BALE_BOT_TOKEN", "token")
    monkeypatch.setenv("CRIER_BALE_CHAT_ID", "7")
    monkeypatch.setenv("CRIER_SMOKE", "1")
    monkeypatch.setattr(requests, "post", lambda *a, **kw: FakeResponse({"ok": True}))

    code = main([])

    assert code == 0
    err = capsys.readouterr().err
    assert "CRIER_OPEN_AI_API_KEY" not in err
    assert "lists" not in err


def test_only_news_without_a_key_reports_it_in_persian(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CRIER_BALE_BOT_TOKEN", "token")
    monkeypatch.setenv("CRIER_BALE_CHAT_ID", "7")

    code = main(["--only", "news"])

    captured = capsys.readouterr()
    assert code == 0
    assert "CRIER_OPEN_AI_API_KEY" in captured.err
    assert any("\u0600" <= char <= "\u06ff" for char in captured.err)
    # «نمی‌شود»: a half-space word written without U+200C still reads as Persian.
    assert "\u200c" in captured.err
    assert "Traceback" not in captured.err


def test_only_news_does_not_warn_about_notes_it_never_asked_for(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("CRIER_BALE_BOT_TOKEN", "token")
    monkeypatch.setenv("CRIER_BALE_CHAT_ID", "7")
    monkeypatch.setenv("CRIER_AVALAI_API_KEY", "aa-key")
    stub_feed(monkeypatch)
    # One HTTP stub covers both posts: Bale reads `ok`, the LLM reads `choices`.
    monkeypatch.setattr(
        requests,
        "post",
        lambda *a, **kw: FakeResponse(
            {"ok": True, "choices": [{"message": {"content": "1|متن یک"}}]}
        ),
    )

    code = main(["--only", "news"])

    assert code == 0
    err = capsys.readouterr().err
    assert "lists" not in err
    assert "CRIER_OPEN_AI_API_KEY" not in err


CHANGEDETECTION_UUID = "7950b31a-25eb-459b-b336-9f4f2affc2dc"
# One added line, in the shape the API returns it.
CHANGEDETECTION_DIFF = '@added_PLACEMARKER_OPEN    "new-model"@added_PLACEMARKER_CLOSED'


def stub_changedetection(monkeypatch, *, last_changed: int = 100):
    """The real client runs; only its HTTP call is faked, as `stub_credit` does."""

    class ApiResponse:
        def __init__(self, *, body=None, text="", status_code=200):
            self._body = body
            self.text = text
            self.status_code = status_code

        def json(self):
            return self._body

    def get(url, **kwargs):
        if "/difference/" in url:
            return ApiResponse(text=CHANGEDETECTION_DIFF)
        return ApiResponse(
            body={
                CHANGEDETECTION_UUID: {
                    "title": "",
                    "url": "https://example.test/models",
                    "last_changed": last_changed,
                }
            }
        )

    monkeypatch.setattr(requests, "get", get)

    # The watcher clears the page's unread dot after a message lands: one PUT per page.
    puts = []

    def put(url, **kwargs):
        puts.append({"url": url, **kwargs})
        return ApiResponse(text="OK")

    monkeypatch.setattr(requests, "put", put)
    return puts


def seed_changedetection(tmp_path, last_changed: int) -> None:
    path = tmp_path / "data" / "watchers.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "changedetection": {
                    "seen": {CHANGEDETECTION_UUID: last_changed},
                    "last_unknown_alert": None,
                }
            }
        ),
        encoding="utf-8",
    )


def test_only_changedetection_selects_the_watcher_alone(tmp_path):
    producers = build_producers(
        settings(changedetection_api_key="cd-key"), memory=memory(tmp_path), only=["changedetection"]
    )

    assert [producer.name for producer in producers] == ["changedetection"]


def test_no_key_means_no_changedetection_watcher_even_under_only(tmp_path):
    producers = build_producers(settings(), memory=memory(tmp_path), only=["changedetection"])

    assert producers == []


def test_the_note_run_leaves_the_changedetection_watcher_out(tmp_path):
    """It owns a timer of its own, so the note run must not touch its watermarks."""
    producers = build_producers(
        settings(changedetection_api_key="cd-key", open_ai_api_key="llm-key"), memory=memory(tmp_path)
    )

    assert [producer.name for producer in producers] == ["note"]


def test_a_changed_page_is_one_watch_bulletin_in_the_history(tmp_path, monkeypatch):
    seed_changedetection(tmp_path, 50)
    stub_changedetection(monkeypatch, last_changed=100)
    send, calls = stub_sender(SendResult(ok=True))

    report = run_once(
        settings(changedetection_api_key="cd-key"),
        now=NOW,
        send=send,
        only=["changedetection"],
    )

    assert report.sent == 1
    assert report.producers == ["changedetection"]
    assert "https://example.test/models" in calls[0]["text"]
    assert '+ "new-model"' in calls[0]["text"]
    records = read_all(path=tmp_path / "data" / "history.jsonl")
    assert len(records) == 1
    assert records[0].kind == "watch"
    assert records[0].ok is True
    blob = json.loads((tmp_path / "data" / "watchers.json").read_text(encoding="utf-8"))
    assert blob["changedetection"]["seen"] == {CHANGEDETECTION_UUID: 100}


def test_a_changedetection_check_with_nothing_new_is_quiet(tmp_path, monkeypatch):
    seed_changedetection(tmp_path, 100)
    stub_changedetection(monkeypatch, last_changed=100)
    send, calls = stub_sender(SendResult(ok=True))

    report = run_once(
        settings(changedetection_api_key="cd-key"),
        now=NOW,
        send=send,
        only=["changedetection"],
    )

    assert calls == []
    assert report.sent == 0


def test_only_changedetection_without_a_key_reports_it_in_persian(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CRIER_BALE_BOT_TOKEN", "token")
    monkeypatch.setenv("CRIER_BALE_CHAT_ID", "7")

    code = main(["--only", "changedetection"])

    captured = capsys.readouterr()
    assert code == 0
    assert "CRIER_CHANGEDETECTION_API_KEY" in captured.err
    assert any("\u0600" <= char <= "\u06ff" for char in captured.err)
    # «نمی‌شود»: a half-space word written without U+200C still reads as Persian.
    assert "\u200c" in captured.err
    assert "Traceback" not in captured.err


def test_a_failed_send_leaves_the_change_for_the_next_run(tmp_path, monkeypatch):
    """The watermark is only recorded when the message landed, so a Bale failure costs
    a repeat rather than the change itself."""
    seed_changedetection(tmp_path, 50)
    stub_changedetection(monkeypatch, last_changed=100)
    failing, _ = stub_sender(SendResult(ok=False, error="chat not found"))

    report = run_once(
        settings(changedetection_api_key="cd-key"),
        now=NOW,
        send=failing,
        only=["changedetection"],
    )

    assert report.failed == 1
    blob = json.loads((tmp_path / "data" / "watchers.json").read_text(encoding="utf-8"))
    assert blob["changedetection"]["seen"] == {CHANGEDETECTION_UUID: 50}

    send, calls = stub_sender(SendResult(ok=True))
    retry = run_once(
        settings(changedetection_api_key="cd-key"),
        now=NOW,
        send=send,
        only=["changedetection"],
    )

    assert retry.sent == 1
    assert len(calls) == 1
    blob = json.loads((tmp_path / "data" / "watchers.json").read_text(encoding="utf-8"))
    assert blob["changedetection"]["seen"] == {CHANGEDETECTION_UUID: 100}


def test_a_changedetection_run_clears_the_dot_of_what_it_sent(tmp_path, monkeypatch):
    seed_changedetection(tmp_path, 50)
    puts = stub_changedetection(monkeypatch, last_changed=100)
    send, _ = stub_sender(SendResult(ok=True))

    run_once(
        settings(changedetection_api_key="cd-key"),
        now=NOW,
        send=send,
        only=["changedetection"],
    )

    assert len(puts) == 1
    assert puts[0]["url"].endswith(f"/api/v1/watch/{CHANGEDETECTION_UUID}")
    assert puts[0]["json"] == {"last_viewed": int(NOW.timestamp())}


def test_a_failed_send_leaves_the_dot_alone(tmp_path, monkeypatch):
    seed_changedetection(tmp_path, 50)
    puts = stub_changedetection(monkeypatch, last_changed=100)
    failing, _ = stub_sender(SendResult(ok=False, error="chat not found"))

    run_once(
        settings(changedetection_api_key="cd-key"),
        now=NOW,
        send=failing,
        only=["changedetection"],
    )

    assert puts == []
