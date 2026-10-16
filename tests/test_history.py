import json
from datetime import datetime, timedelta, timezone

import pytest

from bale_crier.history import append, last_sent_at, read_all
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


def test_last_sent_at_is_none_for_a_note_that_never_went(tmp_path):
    path = tmp_path / "history.jsonl"

    assert last_sent_at(note_id="reading-1", list_name="reading", path=path) is None


def test_last_sent_at_is_the_newest_successful_note(tmp_path):
    path = tmp_path / "history.jsonl"
    append(
        record(kind="note", note_id="reading-1", list_name="reading", ts=NOW),
        path=path,
        max_lines=5000,
    )
    append(
        record(
            kind="note",
            note_id="reading-1",
            list_name="reading",
            ts=NOW + timedelta(days=2),
        ),
        path=path,
        max_lines=5000,
    )

    assert last_sent_at(note_id="reading-1", list_name="reading", path=path) == NOW + timedelta(days=2)


def test_last_sent_at_ignores_failed_and_other_records(tmp_path):
    path = tmp_path / "history.jsonl"
    append(
        record(kind="note", note_id="reading-1", list_name="reading", ts=NOW),
        path=path,
        max_lines=5000,
    )
    append(
        record(
            kind="note",
            note_id="reading-1",
            list_name="reading",
            ts=NOW + timedelta(days=5),
            ok=False,
        ),
        path=path,
        max_lines=5000,
    )
    append(
        record(
            kind="note",
            note_id="reading-1",
            list_name="other",
            ts=NOW + timedelta(days=9),
        ),
        path=path,
        max_lines=5000,
    )
    append(
        record(kind="smoke", note_id="reading-1", ts=NOW + timedelta(days=9)),
        path=path,
        max_lines=5000,
    )

    assert last_sent_at(note_id="reading-1", list_name="reading", path=path) == NOW
