from datetime import datetime, timedelta, timezone
import os

import pytest

from bale_crier.config import Settings
from bale_crier.credit import CreditRead
from bale_crier.memory import WatcherMemory
from bale_crier.models import CreditReport, Package
from bale_crier.watchers.avalai_credit import CreditWatcher

NOW = datetime(2026, 10, 17, 8, 30, tzinfo=timezone.utc)
THRESHOLD = 50_000
FORBIDDEN_ADVICE = ("بخر", "خرید", "توصیه")
# A blocklist can never be complete; it is a guard against the obvious edits to a
# text whose whole job is to say the opposite. The positive assertion below is what
# keeps the sentence itself honest.
GONE_CLAIMS = (
    "تمام شد",
    "تمام شده",
    "به اتمام",
    "اتمام رسید",
    "خالی",
    "صفر است",
    "صفر شد",
    "نمانده",
    "باقی نمانده",
    "موجودی ندارید",
    "ته کشید",
)


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
        "avalai_api_key": "key",
        "credit_threshold_irt": THRESHOLD,
    }
    fields.update(overrides)
    return Settings(**fields)


def report(remaining, *, tier="daily", main=None, packages=()) -> CreditReport:
    return CreditReport(
        main_balance_irt=main,
        packages=list(packages),
        tier_remaining={},
        active_tier=tier,
        active_remaining_irt=remaining,
    )


def ok(remaining, *, tier="daily", packages=()) -> CreditRead:
    return CreditRead(report=report(remaining, tier=tier, packages=packages), error="")


def package(name="وایب کُدر هفتگی پایه", *, tier="weekly", remaining=30_000, left=None):
    """One package ending ``left`` after NOW; ``left=None`` means no end date at all."""
    return Package(
        tier=tier,
        name=name,
        remaining_irt=remaining,
        amount_irt=None,
        end_date=None if left is None else NOW + left,
        spendable=bool(remaining and remaining > 0),
    )


def failed(error="boom") -> CreditRead:
    return CreditRead(report=None, error=error)


class Stub:
    """One queued read per call, so a sequence of runs can be driven."""

    def __init__(self, *reads: CreditRead) -> None:
        self._reads = list(reads)
        self.calls: list[dict] = []

    def __call__(self, **kwargs) -> CreditRead:
        self.calls.append(kwargs)
        if not self._reads:
            raise AssertionError("the watcher read more times than the test supplied")
        return self._reads.pop(0)


def watcher(read: Stub, tmp_path, **overrides) -> CreditWatcher:
    return CreditWatcher(
        settings(**overrides),
        WatcherMemory.load(tmp_path / "watchers.json"),
        read,
    )


def test_the_watcher_is_the_credit_producer_and_owns_its_timer(tmp_path):
    subject = watcher(Stub(), tmp_path)

    assert subject.name == "credit"
    assert subject.own_timer is True


def test_it_reads_with_the_configured_key_and_timeout(tmp_path):
    read = Stub(ok(80_000))
    subject = watcher(read, tmp_path, avalai_api_key="sekret", http_timeout=7)

    subject.produce(NOW)

    assert read.calls == [{"key": "sekret", "timeout": 7}]


def test_the_latch_alerts_once_per_crossing(tmp_path):
    read = Stub(ok(80_000), ok(40_000), ok(30_000), ok(90_000), ok(20_000))
    subject = watcher(read, tmp_path)

    # armed and above the threshold: quiet.
    assert subject.produce(NOW) == []
    # first crossing: exactly one bulletin.
    first = subject.produce(NOW)
    assert len(first) == 1
    assert first[0].kind == "alert"
    assert "40,000" in first[0].text
    # still below, the latch is set: quiet.
    assert subject.produce(NOW) == []
    # back above the threshold: the latch re-arms, still quiet.
    assert subject.produce(NOW) == []
    # the next crossing speaks again.
    second = subject.produce(NOW)
    assert len(second) == 1
    assert second[0].kind == "alert"
    assert "20,000" in second[0].text


def test_a_value_exactly_at_the_threshold_is_quiet_and_keeps_the_latch_armed(tmp_path):
    read = Stub(ok(THRESHOLD), ok(1_000))
    subject = watcher(read, tmp_path)

    # At the threshold is not below it: quiet, and the latch stays armed.
    assert subject.produce(NOW) == []
    assert len(subject.produce(NOW)) == 1


def test_the_first_run_ever_on_a_low_balance_alerts_immediately(tmp_path):
    subject = watcher(Stub(ok(1_000)), tmp_path)

    bulletins = subject.produce(NOW)

    assert len(bulletins) == 1
    assert bulletins[0].kind == "alert"


def test_the_threshold_bulletin_names_the_tier_and_both_numbers(tmp_path):
    subject = watcher(Stub(ok(39_000, tier="weekly")), tmp_path)

    text = subject.produce(NOW)[0].text

    assert "39,000" in text
    assert "50,000" in text
    assert "هفتگی" in text


def test_the_threshold_bulletin_names_the_main_balance_when_no_tier_is_live(tmp_path):
    read = Stub(CreditRead(report=report(30_000, tier=None, main=30_000), error=""))
    subject = watcher(read, tmp_path)

    text = subject.produce(NOW)[0].text

    assert "30,000" in text
    assert "اعتبار اصلی" in text


def test_a_failed_read_speaks_once(tmp_path):
    subject = watcher(Stub(failed("no route to host")), tmp_path)

    bulletins = subject.produce(NOW)

    assert len(bulletins) == 1
    assert bulletins[0].kind == "alert"
    assert bulletins[0].note_id is None


def test_a_repeated_failed_read_is_quiet_inside_the_window(tmp_path):
    read = Stub(failed(), failed(), failed())
    subject = watcher(read, tmp_path)

    assert len(subject.produce(NOW)) == 1
    assert subject.produce(NOW + timedelta(hours=23)) == []
    assert len(subject.produce(NOW + timedelta(hours=25))) == 1


def test_the_unknown_window_follows_the_setting(tmp_path):
    read = Stub(failed(), failed())
    subject = watcher(read, tmp_path, credit_unknown_alert_hours=1)

    assert len(subject.produce(NOW)) == 1
    assert len(subject.produce(NOW + timedelta(hours=2))) == 1


def test_the_window_boundary_itself_counts_as_passed(tmp_path):
    """'At most once every N hours' means it may speak again *at* N, not only after."""
    read = Stub(failed(), failed())
    subject = watcher(read, tmp_path, credit_unknown_alert_hours=1)

    assert len(subject.produce(NOW)) == 1
    assert len(subject.produce(NOW + timedelta(hours=1))) == 1


def test_the_latch_survives_a_process_boundary(tmp_path):
    """Each step is a separate run: load, decide, save. An in-memory latch would
    pass the sequence test above while losing everything between two timers."""
    path = tmp_path / "watchers.json"

    def run(remaining) -> int:
        memory = WatcherMemory.load(path)
        bulletins = CreditWatcher(settings(), memory, Stub(ok(remaining))).produce(NOW)
        memory.save()
        return len(bulletins)

    assert run(80_000) == 0  # armed and above the threshold
    assert run(40_000) == 1  # the crossing speaks
    assert run(30_000) == 0  # still below, and the latch is on disk
    assert run(90_000) == 0  # back above, re-armed
    assert run(20_000) == 1  # and the next crossing speaks again


def test_a_failed_read_does_not_consume_the_crossing(tmp_path):
    read = Stub(ok(80_000), failed(), ok(10_000))
    subject = watcher(read, tmp_path)

    assert subject.produce(NOW) == []
    assert len(subject.produce(NOW)) == 1
    # The latch was armed before the failed read and must still be armed after it.
    assert len(subject.produce(NOW)) == 1


def test_a_failed_read_does_not_re_arm_a_set_latch(tmp_path):
    read = Stub(ok(10_000), failed(), ok(10_000))
    subject = watcher(read, tmp_path)

    assert len(subject.produce(NOW)) == 1
    assert len(subject.produce(NOW)) == 1
    # The crossing was already consumed, and the failed read must not undo that.
    assert subject.produce(NOW) == []


def test_the_unknown_bulletin_says_it_failed_and_never_that_credit_is_gone(tmp_path):
    subject = watcher(Stub(failed()), tmp_path)

    text = subject.produce(NOW)[0].text

    assert "ممکن نشد" in text
    for claim in GONE_CLAIMS:
        assert claim not in text


def test_neither_bulletin_advises_a_purchase(tmp_path):
    threshold = watcher(Stub(ok(1_000)), tmp_path / "threshold").produce(NOW)[0].text
    unknown = watcher(Stub(failed()), tmp_path / "unknown").produce(NOW)[0].text

    for text in (threshold, unknown):
        for word in FORBIDDEN_ADVICE:
            assert word not in text


def test_both_texts_are_persian_with_a_real_half_space(tmp_path):
    threshold = watcher(Stub(ok(1_000)), tmp_path / "threshold").produce(NOW)[0].text
    unknown = watcher(Stub(failed()), tmp_path / "unknown").produce(NOW)[0].text

    for text in (threshold, unknown):
        assert any("\u0600" <= char <= "\u06ff" for char in text)
        # «پایین‌تر» / «نمی‌دانم»: a half-space word written without U+200C still
        # reads as Persian, so only an explicit check notices the character going
        # missing.
        assert "\u200c" in text


def test_the_latch_is_persisted_as_an_aware_utc_timestamp(tmp_path):
    path = tmp_path / "watchers.json"
    memory = WatcherMemory.load(path)

    CreditWatcher(settings(), memory, Stub(failed())).produce(NOW)
    memory.save()

    blob = WatcherMemory.load(path).get("credit")
    assert blob["armed"] is True
    stamp = datetime.fromisoformat(blob["last_unknown_alert"])
    assert stamp.tzinfo is not None
    assert stamp.utcoffset() == timedelta(0)


def test_a_failed_read_keeps_the_latch_it_found(tmp_path):
    path = tmp_path / "watchers.json"
    memory = WatcherMemory.load(path)

    CreditWatcher(settings(), memory, Stub(ok(1_000))).produce(NOW)
    CreditWatcher(settings(), memory, Stub(failed())).produce(NOW)

    assert memory.get("credit")["armed"] is False


def test_a_corrupt_unknown_timestamp_costs_an_alert_not_a_crash(tmp_path):
    path = tmp_path / "watchers.json"
    memory = WatcherMemory.load(path)
    memory.set("credit", {"armed": True, "last_unknown_alert": "not a timestamp"})

    bulletins = CreditWatcher(settings(), memory, Stub(failed())).produce(NOW)

    assert len(bulletins) == 1


def test_a_naive_unknown_timestamp_costs_an_alert_not_a_crash(tmp_path):
    path = tmp_path / "watchers.json"
    memory = WatcherMemory.load(path)
    memory.set("credit", {"armed": True, "last_unknown_alert": "2026-10-17T08:30:00"})

    bulletins = CreditWatcher(settings(), memory, Stub(failed())).produce(NOW)

    assert len(bulletins) == 1


# --- the weekly package's end date ---------------------------------------------------


def test_a_weekly_package_inside_a_day_speaks_before_it_lapses(tmp_path):
    subject = watcher(Stub(ok(80_000, packages=[package(left=timedelta(hours=12))])), tmp_path)

    bulletins = subject.produce(NOW)

    assert len(bulletins) == 1
    assert bulletins[0].kind == "alert"
    text = bulletins[0].text
    assert "هفتگی" in text
    assert "12 ساعت" in text
    assert "30,000" in text
    assert "وایب کُدر هفتگی پایه" in text


def test_the_expiry_notice_speaks_once_per_package(tmp_path):
    read = Stub(
        ok(80_000, packages=[package(left=timedelta(hours=12))]),
        ok(80_000, packages=[package(left=timedelta(hours=12))]),
    )
    subject = watcher(read, tmp_path)

    assert len(subject.produce(NOW)) == 1
    assert subject.produce(NOW + timedelta(hours=1)) == []


def test_a_weekly_package_further_than_the_window_is_quiet(tmp_path):
    subject = watcher(Stub(ok(80_000, packages=[package(left=timedelta(hours=30))])), tmp_path)

    assert subject.produce(NOW) == []


def test_exactly_a_day_left_is_not_yet_inside_the_window(tmp_path):
    subject = watcher(Stub(ok(80_000, packages=[package(left=timedelta(hours=24))])), tmp_path)

    assert subject.produce(NOW) == []


def test_the_expiry_window_follows_the_setting(tmp_path):
    subject = watcher(
        Stub(ok(80_000, packages=[package(left=timedelta(hours=30))])),
        tmp_path,
        credit_expiry_warning_hours=48,
    )

    assert len(subject.produce(NOW)) == 1


def test_a_daily_package_is_never_announced(tmp_path):
    """Its whole life is a day, so a day's warning would be on from the purchase."""
    subject = watcher(
        Stub(ok(80_000, packages=[package(tier="daily", left=timedelta(hours=2))])),
        tmp_path,
    )

    assert subject.produce(NOW) == []


def test_a_weekly_package_with_nothing_left_is_not_news(tmp_path):
    subject = watcher(
        Stub(ok(80_000, packages=[package(remaining=0, left=timedelta(hours=2))])),
        tmp_path,
    )

    assert subject.produce(NOW) == []


def test_a_lapsed_package_is_past_the_notice(tmp_path):
    subject = watcher(
        Stub(ok(80_000, packages=[package(left=timedelta(hours=-1))])),
        tmp_path,
    )

    assert subject.produce(NOW) == []


def test_a_package_without_an_end_date_cannot_be_announced(tmp_path):
    subject = watcher(Stub(ok(80_000, packages=[package(left=None)])), tmp_path)

    assert subject.produce(NOW) == []


def test_two_expiring_packages_share_one_bulletin(tmp_path):
    packages = [
        package("یکی", left=timedelta(hours=5)),
        package("دیگری", left=timedelta(hours=20)),
    ]
    subject = watcher(Stub(ok(80_000, packages=packages)), tmp_path)

    bulletins = subject.produce(NOW)

    assert len(bulletins) == 1
    text = bulletins[0].text
    assert "2 بستهٔ هفتگی" in text
    assert "یکی" in text
    assert "دیگری" in text
    assert "5 ساعت" in text
    assert "20 ساعت" in text


def test_the_threshold_and_the_expiry_can_speak_in_the_same_run(tmp_path):
    read = Stub(ok(40_000, packages=[package(remaining=40_000, left=timedelta(hours=12))]))
    subject = watcher(read, tmp_path)

    bulletins = subject.produce(NOW)

    assert len(bulletins) == 2
    assert "منقضی" in bulletins[0].text
    assert "آستانه" in bulletins[1].text


def test_the_expiry_notice_survives_a_process_boundary(tmp_path):
    path = tmp_path / "watchers.json"
    expiring = package(left=timedelta(hours=12))

    def run(packages) -> int:
        memory = WatcherMemory.load(path)
        bulletins = CreditWatcher(
            settings(), memory, Stub(ok(80_000, packages=packages))
        ).produce(NOW)
        memory.save()
        return len(bulletins)

    assert run([expiring]) == 1
    assert run([expiring]) == 0


def test_a_new_weekly_package_after_the_old_one_lapsed_speaks_again(tmp_path):
    old = package("قدیمی", left=timedelta(hours=12))
    new = package("جدید", left=timedelta(hours=23))
    read = Stub(ok(80_000, packages=[old]), ok(80_000, packages=[old, new]))
    subject = watcher(read, tmp_path)

    assert len(subject.produce(NOW)) == 1
    later = subject.produce(NOW + timedelta(hours=13))
    assert len(later) == 1
    assert "جدید" in later[0].text
    assert "قدیمی" not in later[0].text


def test_a_failed_read_does_not_forget_the_expiry_notice(tmp_path):
    expiring = package(left=timedelta(hours=12))
    read = Stub(
        ok(80_000, packages=[expiring]),
        failed(),
        ok(80_000, packages=[expiring]),
    )
    subject = watcher(read, tmp_path)

    assert len(subject.produce(NOW)) == 1
    assert len(subject.produce(NOW + timedelta(hours=1))) == 1  # the failed read
    assert subject.produce(NOW + timedelta(hours=2)) == []


def test_the_expiry_notice_is_remembered_by_package_and_end_date(tmp_path):
    path = tmp_path / "watchers.json"
    memory = WatcherMemory.load(path)

    CreditWatcher(
        settings(), memory, Stub(ok(80_000, packages=[package(left=timedelta(hours=12))]))
    ).produce(NOW)
    memory.save()

    assert WatcherMemory.load(path).get("credit")["expiry_announced"] == [
        {"name": "وایب کُدر هفتگی پایه", "end_date": (NOW + timedelta(hours=12)).isoformat()}
    ]


def test_a_lapsed_announcement_is_pruned_from_the_memory(tmp_path):
    memory = WatcherMemory.load(tmp_path / "watchers.json")

    CreditWatcher(
        settings(), memory, Stub(ok(80_000, packages=[package(left=timedelta(hours=12))]))
    ).produce(NOW)
    CreditWatcher(settings(), memory, Stub(ok(80_000))).produce(NOW + timedelta(hours=13))

    assert memory.get("credit")["expiry_announced"] == []


def test_a_corrupt_expiry_memory_costs_an_extra_alert_not_a_crash(tmp_path):
    memory = WatcherMemory.load(tmp_path / "watchers.json")
    memory.set("credit", {"armed": True, "expiry_announced": ["nonsense", {"name": None}]})

    bulletins = CreditWatcher(
        settings(), memory, Stub(ok(80_000, packages=[package(left=timedelta(hours=12))]))
    ).produce(NOW)

    assert len(bulletins) == 1


def test_the_notice_gives_the_time_left_in_hours_or_minutes(tmp_path):
    subject = watcher(
        Stub(ok(80_000, packages=[package(left=timedelta(minutes=30))])),
        tmp_path,
    )

    assert "30 دقیقه" in subject.produce(NOW)[0].text


def test_the_expiry_notice_advises_nothing(tmp_path):
    text = watcher(
        Stub(ok(80_000, packages=[package(left=timedelta(hours=12))])), tmp_path
    ).produce(NOW)[0].text

    for word in FORBIDDEN_ADVICE:
        assert word not in text


def test_the_expiry_notice_is_persian_with_a_real_half_space(tmp_path):
    text = watcher(
        Stub(ok(80_000, packages=[package(left=timedelta(hours=12))])), tmp_path
    ).produce(NOW)[0].text

    assert any("\u0600" <= char <= "\u06ff" for char in text)
    assert "\u200c" in text


def test_a_package_whose_balance_cannot_be_read_still_speaks(tmp_path):
    """The end date was read even when the number was not: silence would read as
    "it is empty", which is the one thing a failed read must never become."""
    subject = watcher(
        Stub(ok(80_000, packages=[package(remaining=None, left=timedelta(hours=12))])),
        tmp_path,
    )

    bulletins = subject.produce(NOW)

    assert len(bulletins) == 1
    text = bulletins[0].text
    assert "خوانده نشد" in text
    assert "تومان" not in text


def test_an_unreadable_balance_among_known_ones_keeps_its_own_line(tmp_path):
    packages = [
        package("یکی", left=timedelta(hours=5)),
        package("دیگری", remaining=None, left=timedelta(hours=20)),
    ]
    subject = watcher(Stub(ok(80_000, packages=packages)), tmp_path)

    bulletins = subject.produce(NOW)

    assert len(bulletins) == 1
    assert "یکی" in bulletins[0].text
    assert "30,000 تومان" in bulletins[0].text
    assert "مقدار باقی‌مانده خوانده نشد" in bulletins[0].text


def test_an_unnamed_package_is_still_named_plainly(tmp_path):
    subject = watcher(
        Stub(ok(80_000, packages=[package("", left=timedelta(hours=12))])),
        tmp_path,
    )

    text = subject.produce(NOW)[0].text

    assert "بدون نام" in text
    assert "«»" not in text


def test_an_old_announcement_without_an_offset_still_counts(tmp_path):
    memory = WatcherMemory.load(tmp_path / "watchers.json")
    end = NOW + timedelta(hours=12)
    memory.set(
        "credit",
        {
            "armed": True,
            "expiry_announced": [
                {"name": "وایب کُدر هفتگی پایه", "end_date": end.replace(tzinfo=None).isoformat()}
            ],
        },
    )

    bulletins = CreditWatcher(
        settings(), memory, Stub(ok(80_000, packages=[package(left=timedelta(hours=12))]))
    ).produce(NOW)

    assert bulletins == []
