import os
from datetime import datetime, timedelta, timezone

import pytest

from bale_crier.changedetection import DiffRead, WatchesRead
from bale_crier.config import Settings
from bale_crier.memory import WatcherMemory
from bale_crier.models import Watch
from bale_crier.watchers.changedetection import (
    DIFF_LINES,
    TEXT_CHARS,
    ChangedetectionWatcher,
)

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
ONE_HOUR = 3600
MODELS = "7950b31a-25eb-459b-b336-9f4f2affc2dc"
ZEN = "9a228923-0dc4-4b41-981f-e60f1e3ac6bc"


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
        "changedetection_api_key": "key",
    }
    fields.update(overrides)
    return Settings(**fields)


def watch(uuid=MODELS, url="https://example.test/models", last_changed=0, title="") -> Watch:
    return Watch(uuid=uuid, title=title, url=url, last_changed=last_changed)


class Watches:
    """One queued look at the watch list per call, so a sequence of runs can be driven."""

    def __init__(self, *reads: object) -> None:
        self._reads = list(reads)
        self.calls: list[dict] = []

    def __call__(self, **kwargs) -> WatchesRead:
        self.calls.append(kwargs)
        if not self._reads:
            raise AssertionError("the watcher read more times than the test supplied")
        value = self._reads.pop(0)
        if isinstance(value, WatchesRead):
            return value
        if isinstance(value, Exception):
            raise value
        return WatchesRead(list(value), "")


class Diffs:
    def __init__(self, *reads: DiffRead) -> None:
        self._reads = list(reads)
        self.calls: list[dict] = []

    def __call__(self, **kwargs) -> DiffRead:
        self.calls.append(kwargs)
        if not self._reads:
            raise AssertionError("the watcher read a diff the test did not supply")
        return self._reads.pop(0)


class Marks:
    """The calls the watcher would make to clear a page's unread dot."""

    def __init__(self, *errors: str) -> None:
        self.calls: list[dict] = []
        self._errors = list(errors)

    def __call__(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return self._errors.pop(0) if self._errors else ""


def watcher(read: Watches, tmp_path, diffs: Diffs | None = None, marks: Marks | None = None, **overrides):
    return ChangedetectionWatcher(
        settings(**overrides),
        WatcherMemory.load(tmp_path / "watchers.json"),
        read,
        diffs or Diffs(),
        marks or Marks(),
    )


def primed(tmp_path, **marks: int) -> WatcherMemory:
    """A memory that has already reported these watermarks once.

    Written and re-loaded, so the returned memory owes the file nothing: what a test
    sees after a run is what that run wrote, not what the setup left dirty.
    """
    memory = WatcherMemory.load(tmp_path / "watchers.json")
    memory.set("changedetection", {"seen": dict(marks), "last_unknown_alert": None})
    memory.save()
    return WatcherMemory.load(tmp_path / "watchers.json")


def test_the_watcher_is_the_changedetection_producer_and_owns_its_timer(tmp_path):
    subject = watcher(Watches(), tmp_path)

    assert subject.name == "changedetection"
    assert subject.own_timer is True


def test_it_asks_the_configured_api_with_the_key(tmp_path):
    read = Watches([watch(last_changed=5)])
    watcher(read, tmp_path, changedetection_url="http://127.0.0.1:9999").produce(NOW)

    assert read.calls[0]["base_url"] == "http://127.0.0.1:9999"
    assert read.calls[0]["key"] == "key"


def test_the_first_run_ever_records_the_numbers_and_says_nothing(tmp_path):
    """Everything under watch changed at some point in the past; none of it is news."""
    memory = WatcherMemory.load(tmp_path / "watchers.json")
    subject = ChangedetectionWatcher(
        settings(), memory, Watches([watch(last_changed=1792247965), watch(uuid=ZEN, last_changed=7)])
    )

    assert subject.produce(NOW) == []
    assert memory.get("changedetection")["seen"] == {MODELS: 1792247965, ZEN: 7}


def test_a_moved_watermark_speaks_once(tmp_path):
    memory = primed(tmp_path, **{MODELS: 1792247965})
    subject = ChangedetectionWatcher(
        settings(),
        memory,
        Watches([watch(last_changed=1792247965 + ONE_HOUR)]),
        Diffs(DiffRead(['+ "deepseek-v4.1-flash-free"'], "")),
    )

    bulletins = subject.produce(NOW)

    assert len(bulletins) == 1
    assert bulletins[0].kind == "watch"
    assert "یک صفحه تغییر کرد:" in bulletins[0].text
    assert "https://example.test/models" in bulletins[0].text
    assert '+ "deepseek-v4.1-flash-free"' in bulletins[0].text


def test_the_same_number_again_is_silent(tmp_path):
    memory = primed(tmp_path, **{MODELS: 1792247965})
    subject = ChangedetectionWatcher(
        settings(),
        memory,
        Watches([watch(last_changed=1792247965)], [watch(last_changed=1792247965)]),
    )

    assert subject.produce(NOW) == []
    assert subject.produce(NOW + timedelta(hours=3)) == []


def test_the_bulletin_says_how_long_ago_the_change_was_seen(tmp_path):
    memory = primed(tmp_path, **{MODELS: 1})
    last_changed = int(NOW.timestamp()) - 5400
    subject = ChangedetectionWatcher(
        settings(), memory, Watches([watch(last_changed=last_changed)]), Diffs(DiffRead([], ""))
    )

    assert "۱ ساعت پیش" in subject.produce(NOW)[0].text


def test_a_just_seen_change_says_so_rather_than_zero_minutes(tmp_path):
    memory = primed(tmp_path, **{MODELS: 1})
    subject = ChangedetectionWatcher(
        settings(),
        memory,
        Watches([watch(last_changed=int(NOW.timestamp()) - 5)]),
        Diffs(DiffRead([], "")),
    )

    assert "همین حالا" in subject.produce(NOW)[0].text


def test_a_watch_with_a_title_shows_it_above_the_url(tmp_path):
    memory = primed(tmp_path, **{MODELS: 1})
    subject = ChangedetectionWatcher(
        settings(),
        memory,
        Watches([watch(title="مدل‌های زن", last_changed=10)]),
        Diffs(DiffRead([], "")),
    )

    text = subject.produce(NOW)[0].text

    assert "مدل‌های زن\nhttps://example.test/models" in text


def test_every_changed_page_of_one_run_is_one_bulletin(tmp_path):
    memory = primed(tmp_path, **{MODELS: 1, ZEN: 2})
    subject = ChangedetectionWatcher(
        settings(),
        memory,
        Watches([watch(last_changed=100), watch(uuid=ZEN, url="https://zen.test/models", last_changed=200)]),
        Diffs(DiffRead(['+ "a"'], ""), DiffRead(['+ "b"'], "")),
    )

    bulletins = subject.produce(NOW)

    assert len(bulletins) == 1
    assert "۲ صفحه تغییر کرد:" in bulletins[0].text
    assert "https://example.test/models" in bulletins[0].text
    assert "https://zen.test/models" in bulletins[0].text


def test_the_oldest_change_comes_first(tmp_path):
    """Serving the oldest first is what stops a page waiting behind the ones that
    changed after it: the page deferred this run is the newest, and so goes first next
    run."""
    memory = primed(tmp_path, **{MODELS: 1, ZEN: 2})
    subject = ChangedetectionWatcher(
        settings(),
        memory,
        Watches([watch(last_changed=100), watch(uuid=ZEN, url="https://zen.test/models", last_changed=200)]),
        Diffs(DiffRead([], ""), DiffRead([], "")),
    )

    text = subject.produce(NOW)[0].text

    assert text.index("https://example.test/models") < text.index("https://zen.test/models")


def test_a_watch_seen_for_the_first_time_is_recorded_silently(tmp_path):
    """A page added yesterday may show a change from before it was added; that is not
    news, and it must not arrive as one."""
    memory = primed(tmp_path, **{MODELS: 1})
    subject = ChangedetectionWatcher(
        settings(), memory, Watches([watch(last_changed=1), watch(uuid=ZEN, last_changed=1792247965)])
    )

    assert subject.produce(NOW) == []
    assert memory.get("changedetection")["seen"] == {MODELS: 1, ZEN: 1792247965}


def test_a_cleared_history_going_backwards_is_silent_and_updates_the_number(tmp_path):
    memory = primed(tmp_path, **{MODELS: 1792247965})
    subject = ChangedetectionWatcher(settings(), memory, Watches([watch(last_changed=0)]))

    assert subject.produce(NOW) == []
    assert memory.get("changedetection")["seen"] == {MODELS: 0}


def test_a_watch_deleted_from_changedetection_leaves_no_trace_in_the_next_write(tmp_path):
    memory = primed(tmp_path, **{MODELS: 1, ZEN: 2})
    subject = ChangedetectionWatcher(settings(), memory, Watches([watch(last_changed=1)]))

    subject.produce(NOW)

    assert memory.get("changedetection")["seen"] == {MODELS: 1}


def test_a_failed_read_speaks_once_and_never_as_no_change(tmp_path):
    subject = watcher(Watches(WatchesRead(None, "connection refused")), tmp_path)

    bulletins = subject.produce(NOW)

    assert len(bulletins) == 1
    assert bulletins[0].kind == "alert"
    assert "ممکن نشد" in bulletins[0].text
    assert "connection refused" in bulletins[0].text
    for claim in ("تغییری نکرد", "بدون تغییر", "هیچ تغییری"):
        assert claim not in bulletins[0].text


def test_a_repeated_failed_read_is_quiet_inside_the_window(tmp_path):
    subject = watcher(
        Watches(
            WatchesRead(None, "boom"),
            WatchesRead(None, "boom"),
            WatchesRead(None, "boom"),
        ),
        tmp_path,
    )

    assert len(subject.produce(NOW)) == 1
    assert subject.produce(NOW + timedelta(hours=23)) == []
    assert len(subject.produce(NOW + timedelta(hours=25))) == 1


def test_the_failure_window_follows_the_setting(tmp_path):
    subject = watcher(
        Watches(WatchesRead(None, "boom"), WatchesRead(None, "boom")),
        tmp_path,
        changedetection_unknown_alert_hours=1,
    )

    assert len(subject.produce(NOW)) == 1
    assert len(subject.produce(NOW + timedelta(hours=1))) == 1


def test_a_failed_read_does_not_consume_the_change_it_could_not_see(tmp_path):
    memory = primed(tmp_path, **{MODELS: 1})
    subject = ChangedetectionWatcher(
        settings(),
        memory,
        Watches(WatchesRead(None, "boom"), [watch(last_changed=99)]),
        Diffs(DiffRead(['+ "x"'], "")),
    )

    assert len(subject.produce(NOW)) == 1  # the failure speaks
    assert len(subject.produce(NOW)) == 1  # and the change still arrives afterwards
    assert memory.get("changedetection")["seen"] == {MODELS: 99}


def test_a_change_is_reported_even_when_its_diff_cannot_be_read(tmp_path):
    """The change is real — `last_changed` says so. A missing diff costs the detail,
    never the message."""
    memory = primed(tmp_path, **{MODELS: 1})
    subject = ChangedetectionWatcher(
        settings(),
        memory,
        Watches([watch(last_changed=99)]),
        Diffs(DiffRead(None, "timeout")),
    )

    text = subject.produce(NOW)[0].text

    assert "https://example.test/models" in text
    assert "متن تغییر خوانده نشد" in text


def test_more_changed_lines_than_fit_are_cut_with_a_count(tmp_path):
    memory = primed(tmp_path, **{MODELS: 1})
    many = DiffRead([f"+ line {index}" for index in range(DIFF_LINES + 3)], "")
    subject = ChangedetectionWatcher(settings(), memory, Watches([watch(last_changed=99)]), Diffs(many))

    text = subject.produce(NOW)[0].text

    assert "line 9" in text
    assert "line 10" not in text
    assert "۳ خط دیگر" in text


def test_one_runaway_line_is_clipped(tmp_path):
    memory = primed(tmp_path, **{MODELS: 1})
    subject = ChangedetectionWatcher(
        settings(),
        memory,
        Watches([watch(last_changed=99)]),
        Diffs(DiffRead([f"+ {'x' * 5000}"], "")),
    )

    text = subject.produce(NOW)[0].text

    assert len(text) <= TEXT_CHARS
    assert "…" in text


def test_a_whole_run_of_changed_pages_stays_inside_one_message(tmp_path):
    """Six pages each with a full diff must not produce a message Bale refuses."""
    memory = primed(tmp_path, **{f"u{index}": 1 for index in range(6)})
    pages = [watch(uuid=f"u{index}", url=f"https://example.test/{index}", last_changed=99) for index in range(6)]
    diffs = Diffs(*[DiffRead([f"+ {'y' * 190}"] * DIFF_LINES, "") for _ in range(6)])
    subject = ChangedetectionWatcher(settings(), memory, Watches(pages), diffs)

    text = subject.produce(NOW)[0].text

    assert len(text) <= TEXT_CHARS
    assert "در پیام بعدی" in text


def test_a_page_that_does_not_fit_keeps_its_number_so_the_next_run_carries_it(tmp_path):
    """The last line promises the rest next time. Leaving their numbers alone is
    necessary for that — advancing them would consume a change the owner never read —
    and the oldest-first order is what actually makes it happen; the test below drives
    the case where a page changes again in the meantime."""
    memory = primed(tmp_path, **{f"u{index}": 1 for index in range(6)})
    pages = [watch(uuid=f"u{index}", url=f"https://example.test/{index}", last_changed=99) for index in range(6)]
    diffs = Diffs(*[DiffRead([f"+ {'y' * 190}"] * DIFF_LINES, "") for _ in range(12)])
    subject = ChangedetectionWatcher(settings(), memory, Watches(pages, pages), diffs)

    text = subject.produce(NOW)[0].text
    seen = memory.get("changedetection")["seen"]
    carried = [uuid for uuid, mark in seen.items() if mark == 99]

    assert "در پیام بعدی" in text
    assert len(carried) == 1
    # The next run starts from the ones still owed, not from the whole list again.
    subject.produce(NOW)
    seen = memory.get("changedetection")["seen"]
    assert len([uuid for uuid, mark in seen.items() if mark == 99]) == 2


def test_one_page_too_long_for_a_message_is_clipped_but_still_named(tmp_path):
    memory = primed(tmp_path, **{MODELS: 1})
    long_url = f"https://example.test/{'z' * 4000}"
    subject = ChangedetectionWatcher(
        settings(),
        memory,
        Watches([watch(url=long_url, last_changed=99)]),
        Diffs(DiffRead([f"+ {'y' * 200}"] * 40, "")),
    )

    text = subject.produce(NOW)[0].text

    assert len(text) <= TEXT_CHARS
    assert text.startswith("یک صفحه تغییر کرد:")
    assert long_url[:200] in text
    assert "…" in text


def test_a_rewritten_page_shows_both_what_went_and_what_came(tmp_path):
    """changedetection renders a rewritten page as all the old lines then all the new
    ones, so a plain first-ten cut would show ten removals and not one addition."""
    memory = primed(tmp_path, **{MODELS: 1})
    old = [f'- "old {index}"' for index in range(60)]
    new = [f'+ "new {index}"' for index in range(60)]
    subject = ChangedetectionWatcher(
        settings(), memory, Watches([watch(last_changed=99)]), Diffs(DiffRead(old + new, ""))
    )

    text = subject.produce(NOW)[0].text

    assert '- "old 0"' in text
    assert '+ "new 0"' in text
    assert text.index('- "old 0"') < text.index('+ "new 0"')
    assert "۱۱۰ خط دیگر" in text


def test_a_watch_with_nothing_to_diff_says_so(tmp_path):
    """A single snapshot has nothing to compare against: the change is real, the text
    is simply not there — which is not the same as a failed read."""
    memory = primed(tmp_path, **{MODELS: 1})
    subject = ChangedetectionWatcher(
        settings(), memory, Watches([watch(last_changed=99)]), Diffs(DiffRead([], ""))
    )

    text = subject.produce(NOW)[0].text

    assert "https://example.test/models" in text
    assert "متن تغییر در دسترس نیست" in text
    assert "خوانده نشد" not in text


def test_the_failure_text_is_persian_with_a_real_half_space(tmp_path):
    text = watcher(Watches(WatchesRead(None, "boom")), tmp_path).produce(NOW)[0].text

    assert any("\u0600" <= char <= "\u06ff" for char in text)
    # «نمی‌دانم»: without U+200C it still reads as Persian, so only an explicit check
    # notices the character going missing.
    assert "\u200c" in text


def test_the_watermarks_survive_a_process_boundary(tmp_path):
    """Each step is a separate run: load, decide, save. An in-memory watermark would
    re-send every change on every tick."""
    path = tmp_path / "watchers.json"

    def run(*watches) -> int:
        memory = WatcherMemory.load(path)
        subject = ChangedetectionWatcher(
            settings(), memory, Watches(list(watches)), Diffs(*[DiffRead([], "")] * len(watches))
        )
        count = len(subject.produce(NOW))
        memory.save()
        return count

    assert run(watch(last_changed=100)) == 0  # baseline
    assert run(watch(last_changed=100)) == 0  # nothing new
    assert run(watch(last_changed=200)) == 1  # the change speaks
    assert run(watch(last_changed=200)) == 0  # and does not speak again


def test_a_corrupt_watermark_costs_one_bulletin_not_a_crash(tmp_path):
    memory = WatcherMemory.load(tmp_path / "watchers.json")
    memory.set("changedetection", {"seen": {MODELS: "not a number"}})
    subject = ChangedetectionWatcher(
        settings(), memory, Watches([watch(last_changed=99)]), Diffs(DiffRead([], ""))
    )

    assert len(subject.produce(NOW)) == 1


def test_a_missing_watermark_map_is_a_first_run_not_a_crash(tmp_path):
    memory = WatcherMemory.load(tmp_path / "watchers.json")
    memory.set("changedetection", {"last_unknown_alert": "2026-10-21T10:00:00+00:00"})
    subject = ChangedetectionWatcher(settings(), memory, Watches([watch(last_changed=99)]))

    assert subject.produce(NOW) == []
    assert memory.get("changedetection")["seen"] == {MODELS: 99}


def test_a_quiet_run_leaves_the_memory_file_untouched(tmp_path):
    """A run that learned nothing new must not rewrite the file: a quiet tick should be
    invisible on disk as well as in the chat. The write goes through a rename, so a
    rewrite shows up as a new inode."""
    path = tmp_path / "watchers.json"
    memory = primed(tmp_path, **{MODELS: 5})
    before = path.stat().st_ino
    subject = ChangedetectionWatcher(settings(), memory, Watches([watch(last_changed=5)]))

    subject.produce(NOW)
    memory.save()

    assert path.stat().st_ino == before


def test_a_page_left_over_is_served_next_run_even_when_another_changes_again(tmp_path):
    """The deferral cannot starve: the page left over is the newest of that run, and the
    oldest of the next, so it goes first — even if the page that beat it changed again."""
    memory = primed(tmp_path, **{MODELS: 1, ZEN: 2})
    huge = DiffRead([f"+ {'y' * 190}"] * DIFF_LINES, "")
    subject = ChangedetectionWatcher(
        settings(),
        memory,
        Watches(
            [watch(last_changed=100), watch(uuid=ZEN, url="https://zen.test/models", last_changed=200)],
            # The same two pages: the one that got in changed again, the one left over
            # did not, so the left-over page is now the older of the two.
            [watch(last_changed=300), watch(uuid=ZEN, url="https://zen.test/models", last_changed=200)],
        ),
        Diffs(huge, huge, huge, huge),
    )

    first = subject.produce(NOW)[0].text
    second = subject.produce(NOW)[0].text

    assert "https://example.test/models" in first
    assert "https://zen.test/models" not in first
    assert "https://zen.test/models" in second


def one_changed_page(tmp_path, **overrides):
    memory = primed(tmp_path, **{MODELS: 1})
    marks = Marks()
    subject = ChangedetectionWatcher(
        settings(**overrides),
        memory,
        Watches([watch(last_changed=99)]),
        Diffs(DiffRead(['+ "x"'], "")),
        marks,
    )
    return subject, marks


def test_a_landed_message_clears_the_dot_of_the_pages_it_named(tmp_path):
    subject, marks = one_changed_page(tmp_path, changedetection_url="http://127.0.0.1:9999")

    subject.produce(NOW)
    subject.sent(ok=True, now=NOW)

    assert len(marks.calls) == 1
    assert marks.calls[0]["uuid"] == MODELS
    assert marks.calls[0]["at"] == int(NOW.timestamp())
    assert marks.calls[0]["base_url"] == "http://127.0.0.1:9999"
    assert marks.calls[0]["key"] == "key"


def test_the_mark_is_never_older_than_the_change_it_marks(tmp_path):
    """A clock behind the snapshot's would leave the dot on, so the change time is the
    floor."""
    memory = primed(tmp_path, **{MODELS: 1})
    marks = Marks()
    ahead = int(NOW.timestamp()) + 3600
    subject = ChangedetectionWatcher(
        settings(), memory, Watches([watch(last_changed=ahead)]), Diffs(DiffRead([], "")), marks
    )

    subject.produce(NOW)
    subject.sent(ok=True, now=NOW)

    assert marks.calls[0]["at"] == ahead


def test_a_failed_send_marks_nothing_and_remembers_nothing(tmp_path):
    """The dot is the UI's record of "Bale has not told me yet": a failed send repeats
    next run, so it must not go out now."""
    subject, marks = one_changed_page(tmp_path)

    subject.produce(NOW)
    subject.sent(ok=False, now=NOW)
    subject.sent(ok=True, now=NOW)

    assert marks.calls == []


def test_a_quiet_run_marks_nothing(tmp_path):
    memory = primed(tmp_path, **{MODELS: 5})
    marks = Marks()
    subject = ChangedetectionWatcher(settings(), memory, Watches([watch(last_changed=5)]), Diffs(), marks)

    subject.produce(NOW)
    subject.sent(ok=True, now=NOW)

    assert marks.calls == []


def test_a_failed_read_marks_nothing(tmp_path):
    marks = Marks()
    subject = ChangedetectionWatcher(
        settings(), WatcherMemory.load(tmp_path / "w.json"), Watches(WatchesRead(None, "boom")), Diffs(), marks
    )

    subject.produce(NOW)
    subject.sent(ok=True, now=NOW)

    assert marks.calls == []


def test_a_page_that_did_not_fit_the_message_keeps_its_dot(tmp_path):
    """Only the pages the message actually named were told; the one left over was not."""
    memory = primed(tmp_path, **{MODELS: 1, ZEN: 2})
    huge = DiffRead([f"+ {'y' * 190}"] * DIFF_LINES, "")
    marks = Marks()
    subject = ChangedetectionWatcher(
        settings(),
        memory,
        Watches([watch(last_changed=100), watch(uuid=ZEN, url="https://zen.test/models", last_changed=200)]),
        Diffs(huge, huge),
        marks,
    )

    subject.produce(NOW)
    subject.sent(ok=True, now=NOW)

    assert [call["uuid"] for call in marks.calls] == [MODELS]


def test_a_mark_that_fails_does_not_stop_the_next_one(tmp_path):
    memory = primed(tmp_path, **{MODELS: 1, ZEN: 2})
    marks = Marks("changedetection پاسخ 500 داد.")
    subject = ChangedetectionWatcher(
        settings(),
        memory,
        Watches([watch(last_changed=100), watch(uuid=ZEN, url="https://zen.test/models", last_changed=200)]),
        Diffs(DiffRead([], ""), DiffRead([], "")),
        marks,
    )

    subject.produce(NOW)
    subject.sent(ok=True, now=NOW)

    assert [call["uuid"] for call in marks.calls] == [MODELS, ZEN]
