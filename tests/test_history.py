import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bale_crier.history import append, last_sent_map, previous_texts, read_all
from bale_crier.models import HistoryRecord

NOW = datetime(2026, 10, 17, 8, 30, tzinfo=timezone.utc)


def record(**overrides) -> HistoryRecord:
    fields = {
        "ts": NOW,
        "kind": "smoke",
        "text": "متن آزمایشی",
        "ok": True,
    }
    fields.update(overrides)
    return HistoryRecord(**fields)


def send(path: Path, **overrides) -> None:
    """One successful note record, unless an override says otherwise."""
    fields = {"kind": "note", "note_id": "reading-1", "list_name": "reading"}
    fields.update(overrides)
    append(record(**fields), path=path, max_lines=5000)


def test_append_creates_the_directory_and_the_file(tmp_path):
    path = tmp_path / "data" / "history.jsonl"

    append(record(), path=path, max_lines=5000)

    assert path.is_file()


def test_two_appends_leave_two_parseable_lines(tmp_path):
    path = tmp_path / "history.jsonl"

    append(record(text="اول"), path=path, max_lines=5000)
    append(record(text="دوم"), path=path, max_lines=5000)

    lines = path.read_text(encoding="utf-8").splitlines()

    assert [json.loads(line)["text"] for line in lines] == ["اول", "دوم"]


def test_read_all_on_a_missing_path_is_empty(tmp_path):
    assert read_all(path=tmp_path / "absent.jsonl") == []


def test_a_broken_line_is_skipped_and_the_records_after_it_survive(tmp_path):
    """A killed write leaves a fragment, and the next append lands after it."""
    path = tmp_path / "history.jsonl"
    append(record(text="اول"), path=path, max_lines=5000)
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"ts": "2026-10-17T08:30:00Z", "kind": "smoke", "te')
    append(record(text="دوم"), path=path, max_lines=5000)

    records = read_all(path=path)

    assert [item.text for item in records] == ["اول", "دوم"]


def test_the_cap_keeps_the_newest_lines_in_order(tmp_path):
    path = tmp_path / "history.jsonl"

    for index in range(4):
        append(record(text=f"متن {index}"), path=path, max_lines=3)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert [item.text for item in read_all(path=path)] == ["متن 1", "متن 2", "متن 3"]
    # The trim goes through a neighbour file and a rename; it must not leave the
    # neighbour behind.
    assert list(path.parent.glob("*.tmp")) == []


def test_the_timestamp_survives_the_round_trip_as_aware_utc(tmp_path):
    path = tmp_path / "history.jsonl"

    append(record(ts=NOW), path=path, max_lines=5000)
    stored = read_all(path=path)[0].ts

    assert stored == NOW
    assert stored.tzinfo is not None
    assert stored.utcoffset() == timedelta(0)


def test_a_naive_timestamp_is_read_as_utc_not_as_the_boxs_local_time(tmp_path):
    path = tmp_path / "history.jsonl"
    naive = datetime(2026, 10, 17, 8, 30)

    append(record(ts=naive), path=path, max_lines=5000)
    stored = read_all(path=path)[0].ts

    assert stored == naive.replace(tzinfo=timezone.utc)
    assert stored.utcoffset() == timedelta(0)


def test_a_timestamp_from_another_zone_is_converted_to_utc(tmp_path):
    path = tmp_path / "history.jsonl"
    tehran = timezone(timedelta(hours=3, minutes=30))

    append(record(ts=datetime(2026, 10, 17, 12, 0, tzinfo=tehran)), path=path, max_lines=5000)
    stored = read_all(path=path)[0].ts

    assert stored == datetime(2026, 10, 17, 8, 30, tzinfo=timezone.utc)
    assert stored.utcoffset() == timedelta(0)


def test_a_cap_below_one_is_refused_before_anything_is_written(tmp_path):
    path = tmp_path / "history.jsonl"
    append(record(), path=path, max_lines=5000)

    with pytest.raises(ValueError):
        append(record(), path=path, max_lines=0)

    assert len(read_all(path=path)) == 1


def test_last_sent_map_on_a_missing_file_is_empty(tmp_path):
    assert last_sent_map(path=tmp_path / "absent.jsonl") == {}


def test_last_sent_map_keeps_the_newest_timestamp_when_a_note_went_twice(tmp_path):
    path = tmp_path / "history.jsonl"
    send(path, ts=NOW)
    send(path, ts=NOW + timedelta(days=2))

    assert last_sent_map(path=path) == {("reading", "reading-1"): NOW + timedelta(days=2)}


def test_last_sent_map_ignores_failed_other_kind_and_note_less_records(tmp_path):
    path = tmp_path / "history.jsonl"
    send(path, ts=NOW)
    send(path, ts=NOW + timedelta(days=5), ok=False)
    send(path, ts=NOW + timedelta(days=9), kind="alert")
    send(path, ts=NOW + timedelta(days=9), note_id=None)

    assert last_sent_map(path=path) == {("reading", "reading-1"): NOW}


def test_last_sent_map_separates_the_same_id_in_two_lists(tmp_path):
    path = tmp_path / "history.jsonl"
    send(path, ts=NOW)
    send(path, ts=NOW + timedelta(days=1), list_name="habits")

    assert last_sent_map(path=path) == {
        ("reading", "reading-1"): NOW,
        ("habits", "reading-1"): NOW + timedelta(days=1),
    }


def test_previous_texts_gives_the_newest_limit_oldest_first(tmp_path):
    path = tmp_path / "history.jsonl"
    send(path, ts=NOW, text="اول")
    send(path, ts=NOW + timedelta(days=1), text="دوم")
    send(path, ts=NOW + timedelta(days=2), text="سوم")

    assert previous_texts(
        path=path, note_id="reading-1", list_name="reading", limit=2
    ) == ["دوم", "سوم"]


def test_previous_texts_is_empty_for_a_note_that_never_went_and_ignores_failures(tmp_path):
    path = tmp_path / "history.jsonl"
    send(path, ts=NOW, note_id="other")
    send(path, ts=NOW + timedelta(days=1), ok=False, text="متن‌ها")

    assert previous_texts(
        path=path, note_id="reading-1", list_name="reading", limit=3
    ) == []


def test_previous_texts_orders_by_timestamp_not_by_file_order(tmp_path):
    path = tmp_path / "history.jsonl"
    send(path, ts=NOW + timedelta(days=2), text="دیرتر")
    send(path, ts=NOW, text="زودتر")

    assert previous_texts(
        path=path, note_id="reading-1", list_name="reading", limit=5
    ) == ["زودتر", "دیرتر"]


def test_previous_texts_with_a_limit_beyond_the_records_gives_them_all(tmp_path):
    path = tmp_path / "history.jsonl"
    send(path, ts=NOW, text="اول")
    send(path, ts=NOW + timedelta(days=1), text="دوم")

    assert previous_texts(
        path=path, note_id="reading-1", list_name="reading", limit=9
    ) == ["اول", "دوم"]


def test_previous_texts_with_a_limit_below_one_gives_nothing(tmp_path):
    """A slice of ``-0`` would otherwise be the whole list, not an empty one."""
    path = tmp_path / "history.jsonl"
    send(path, ts=NOW, text="اول")

    assert previous_texts(
        path=path, note_id="reading-1", list_name="reading", limit=0
    ) == []
