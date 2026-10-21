from datetime import datetime, timedelta, timezone
import os

import pytest

from bale_crier.config import Settings
from bale_crier.memory import WatcherMemory
from bale_crier.watchers.disk import DiskWatcher

NOW = datetime(2026, 10, 17, 8, 30, tzinfo=timezone.utc)
GIB = 1024**3
THRESHOLD = 2 * GIB
# A blocklist can never be complete; it guards against the obvious edit to a text
# whose job is to say the opposite. The positive assertion below keeps it honest.
FULL_CLAIMS = ("پر شد", "پر است", "تمام شد", "خالی نمانده", "فضا ندارد")


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
        "disk_threshold_gib": 2,
    }
    fields.update(overrides)
    return Settings(**fields)


class Stub:
    """One queued read per call, so a sequence of runs can be driven."""

    def __init__(self, *reads: object) -> None:
        self._reads = list(reads)
        self.calls: list = []

    def __call__(self, path) -> int:
        self.calls.append(path)
        if not self._reads:
            raise AssertionError("the watcher read more times than the test supplied")
        value = self._reads.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def watcher(read: Stub, tmp_path, **overrides) -> DiskWatcher:
    return DiskWatcher(
        settings(**overrides),
        WatcherMemory.load(tmp_path / "watchers.json"),
        read,
    )


def test_the_watcher_is_the_disk_producer_and_owns_its_timer(tmp_path):
    subject = watcher(Stub(), tmp_path)

    assert subject.name == "disk"
    assert subject.own_timer is True


def test_it_reads_the_configured_path(tmp_path):
    read = Stub(3 * GIB)
    subject = watcher(read, tmp_path, disk_path=tmp_path)

    subject.produce(NOW)

    assert read.calls == [tmp_path]


def test_the_latch_alerts_once_per_crossing(tmp_path):
    read = Stub(3 * GIB, 1 * GIB, 500 * 1024**2, 4 * GIB, 100 * 1024**2)
    subject = watcher(read, tmp_path)

    # armed and above the threshold: quiet.
    assert subject.produce(NOW) == []
    # first crossing: exactly one bulletin.
    first = subject.produce(NOW)
    assert len(first) == 1
    assert first[0].kind == "alert"
    assert first[0].text.startswith("فضای آزاد دیسک از آستانه پایین‌تر آمد: 1 گیگابایت")
    # still below, the latch is set: quiet.
    assert subject.produce(NOW) == []
    # back above the threshold: the latch re-arms, still quiet.
    assert subject.produce(NOW) == []
    # the next crossing speaks again.
    second = subject.produce(NOW)
    assert len(second) == 1
    assert second[0].kind == "alert"
    assert "0.09 گیگابایت" in second[0].text


def test_a_value_exactly_at_the_threshold_is_quiet_and_keeps_the_latch_armed(tmp_path):
    read = Stub(THRESHOLD, 1 * GIB)
    subject = watcher(read, tmp_path)

    # At the threshold is not below it: quiet, and the latch stays armed.
    assert subject.produce(NOW) == []
    assert len(subject.produce(NOW)) == 1


def test_the_first_run_ever_on_a_low_disk_alerts_immediately(tmp_path):
    subject = watcher(Stub(1 * GIB), tmp_path)

    bulletins = subject.produce(NOW)

    assert len(bulletins) == 1
    assert bulletins[0].kind == "alert"


def test_the_crossing_bulletin_names_the_free_space_and_the_threshold(tmp_path):
    subject = watcher(Stub(int(1.5 * GIB)), tmp_path)

    text = subject.produce(NOW)[0].text

    assert "1.5 گیگابایت" in text
    assert "آستانه 2 گیگابایت" in text


def test_a_fractional_threshold_is_shown_as_it_was_set(tmp_path):
    """The setting and the bulletin must not disagree: 2.5 GiB is not «2»."""
    subject = watcher(Stub(int(1.5 * GIB)), tmp_path, disk_threshold_gib=2.5)

    text = subject.produce(NOW)[0].text

    assert "1.5 گیگابایت خالی مانده" in text
    assert "آستانه 2.5 گیگابایت" in text


def test_the_free_space_is_never_rounded_up_to_the_threshold(tmp_path):
    """One byte below 2 GiB must not print as «2 گیگابایت … آستانه 2 گیگابایت»."""
    subject = watcher(Stub(THRESHOLD - 1), tmp_path)

    text = subject.produce(NOW)[0].text

    assert "1.99 گیگابایت خالی مانده" in text


def test_staying_below_speaks_again_only_after_the_reminder_window(tmp_path):
    read = Stub(1 * GIB, 1 * GIB, 1 * GIB)
    subject = watcher(read, tmp_path)

    assert len(subject.produce(NOW)) == 1
    assert subject.produce(NOW + timedelta(hours=23)) == []
    assert len(subject.produce(NOW + timedelta(hours=24))) == 1


def test_the_reminder_window_moves_forward_with_each_reminder(tmp_path):
    """A reminder that did not move the window forward would speak every hour
    after the first day; the window is anchored to the last message, not the
    crossing."""
    read = Stub(1 * GIB, 1 * GIB, 1 * GIB, 1 * GIB)
    subject = watcher(read, tmp_path)

    assert len(subject.produce(NOW)) == 1
    assert len(subject.produce(NOW + timedelta(hours=24))) == 1
    assert subject.produce(NOW + timedelta(hours=25)) == []
    assert len(subject.produce(NOW + timedelta(hours=48))) == 1


def test_the_reminder_window_follows_the_setting(tmp_path):
    read = Stub(1 * GIB, 1 * GIB)
    subject = watcher(read, tmp_path, disk_reminder_hours=1)

    assert len(subject.produce(NOW)) == 1
    assert len(subject.produce(NOW + timedelta(hours=1))) == 1


def test_the_reminder_says_the_disk_is_still_low(tmp_path):
    read = Stub(1 * GIB, 1 * GIB)
    subject = watcher(read, tmp_path, disk_reminder_hours=1)

    first = subject.produce(NOW)[0].text
    reminder = subject.produce(NOW + timedelta(hours=1))[0].text

    assert "پایین‌تر آمد" in first
    assert "هنوز پایین‌تر" in reminder


def test_a_failed_read_speaks_once(tmp_path):
    subject = watcher(Stub(OSError("no such path")), tmp_path)

    bulletins = subject.produce(NOW)

    assert len(bulletins) == 1
    assert bulletins[0].kind == "alert"


def test_a_repeated_failed_read_is_quiet_inside_the_window(tmp_path):
    read = Stub(OSError("boom"), OSError("boom"), OSError("boom"))
    subject = watcher(read, tmp_path)

    assert len(subject.produce(NOW)) == 1
    assert subject.produce(NOW + timedelta(hours=23)) == []
    assert len(subject.produce(NOW + timedelta(hours=25))) == 1


def test_a_failed_read_does_not_consume_the_crossing(tmp_path):
    read = Stub(3 * GIB, OSError("boom"), 1 * GIB)
    subject = watcher(read, tmp_path)

    assert subject.produce(NOW) == []
    # The failed read speaks, and the latch is still armed underneath it.
    assert len(subject.produce(NOW)) == 1
    assert len(subject.produce(NOW)) == 1


def test_a_failed_read_does_not_re_arm_a_set_latch(tmp_path):
    read = Stub(1 * GIB, OSError("boom"), 1 * GIB)
    subject = watcher(read, tmp_path)

    assert len(subject.produce(NOW)) == 1
    # Inside the window the failed read is quiet, and must not undo the crossing.
    assert subject.produce(NOW) == []
    assert subject.produce(NOW) == []


def test_the_unknown_bulletin_says_it_failed_and_never_that_the_disk_is_full(tmp_path):
    subject = watcher(Stub(OSError("boom")), tmp_path)

    text = subject.produce(NOW)[0].text

    assert "ممکن نشد" in text
    for claim in FULL_CLAIMS:
        assert claim not in text


def test_all_three_texts_are_persian_with_a_real_half_space(tmp_path):
    crossing = watcher(Stub(1 * GIB), tmp_path / "crossing").produce(NOW)[0].text
    reminder_read = Stub(1 * GIB, 1 * GIB)
    reminder_subject = watcher(reminder_read, tmp_path / "reminder", disk_reminder_hours=1)
    reminder_subject.produce(NOW)
    reminder = reminder_subject.produce(NOW + timedelta(hours=1))[0].text
    unknown = watcher(Stub(OSError("boom")), tmp_path / "unknown").produce(NOW)[0].text

    for text in (crossing, reminder, unknown):
        assert any("\u0600" <= char <= "\u06ff" for char in text)
        # «پایین‌تر» / «نمی‌دانم»: a half-space word written without U+200C still
        # reads as Persian, so only an explicit check notices the character going
        # missing.
        assert "\u200c" in text


def test_the_latch_survives_a_process_boundary(tmp_path):
    """Each step is a separate run: load, decide, save. An in-memory latch would
    pass the sequence test above while losing everything between two timers."""
    path = tmp_path / "watchers.json"

    def run(free) -> int:
        memory = WatcherMemory.load(path)
        bulletins = DiskWatcher(settings(), memory, Stub(free)).produce(NOW)
        memory.save()
        return len(bulletins)

    assert run(3 * GIB) == 0  # armed and above the threshold
    assert run(1 * GIB) == 1  # the crossing speaks
    assert run(1 * GIB) == 0  # still below, and the latch is on disk
    assert run(4 * GIB) == 0  # back above, re-armed
    assert run(1 * GIB) == 1  # and the next crossing speaks again


def test_the_latch_is_persisted_as_an_aware_utc_timestamp(tmp_path):
    path = tmp_path / "watchers.json"
    memory = WatcherMemory.load(path)

    DiskWatcher(settings(), memory, Stub(OSError("boom"))).produce(NOW)
    memory.save()

    blob = WatcherMemory.load(path).get("disk")
    assert blob["armed"] is True
    stamp = datetime.fromisoformat(blob["last_alert"])
    assert stamp.tzinfo is not None
    assert stamp.utcoffset() == timedelta(0)


def test_a_failed_read_keeps_the_latch_it_found(tmp_path):
    path = tmp_path / "watchers.json"
    memory = WatcherMemory.load(path)

    DiskWatcher(settings(), memory, Stub(1 * GIB)).produce(NOW)
    DiskWatcher(settings(), memory, Stub(OSError("boom"))).produce(NOW)

    assert memory.get("disk")["armed"] is False


def test_a_corrupt_reminder_timestamp_costs_an_alert_not_a_crash(tmp_path):
    memory = WatcherMemory.load(tmp_path / "watchers.json")
    memory.set("disk", {"armed": False, "last_alert": "not a timestamp"})

    bulletins = DiskWatcher(settings(), memory, Stub(1 * GIB)).produce(NOW)

    assert len(bulletins) == 1


def test_a_naive_reminder_timestamp_costs_an_alert_not_a_crash(tmp_path):
    memory = WatcherMemory.load(tmp_path / "watchers.json")
    memory.set("disk", {"armed": False, "last_alert": "2026-10-17T08:30:00"})

    bulletins = DiskWatcher(settings(), memory, Stub(1 * GIB)).produce(NOW)

    assert len(bulletins) == 1
