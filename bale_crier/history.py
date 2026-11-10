"""The history: append-only JSONL, one line per bulletin.

Appending is the whole write path, so a crash cannot lose the records already
written. The size cap is the one exception — when the file grows past it, the
newest lines are rewritten through a rename, never by truncating first.
"""

from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from .jsonl import append_line, read_lines
from .models import HistoryRecord


def as_utc(ts: datetime) -> datetime:
    """A naive timestamp is read as UTC, never as the box's local time.

    Reading it as UTC keeps a stored time from shifting when the machine's
    timezone changes; an aware timestamp is converted to UTC instead.
    """
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def append(record: HistoryRecord, *, path: Path, max_lines: int) -> None:
    stored = record.model_copy(update={"ts": as_utc(record.ts)})
    append_line(stored.model_dump_json(), path=path, max_lines=max_lines)


def read_all(*, path: Path) -> list[HistoryRecord]:
    records: list[HistoryRecord] = []
    for line in read_lines(path=path):
        if not line.strip():
            continue
        try:
            records.append(HistoryRecord.model_validate_json(line))
        except ValueError:
            # A run killed mid-write leaves one broken line; the rest is intact.
            # pydantic's ValidationError is a ValueError, so one clause covers both.
            continue
    return records


def _sent_notes(records: Iterable[HistoryRecord]):
    """The records that mean a note actually went, keyed by the note's identity."""
    for record in records:
        if record.kind == "note" and record.ok and record.note_id and record.list_name:
            yield (record.list_name, record.note_id), record


def last_sent_map(*, path: Path) -> dict[tuple[str, str], datetime]:
    """The newest successful ``note`` timestamp per ``(list_name, note_id)``."""
    latest: dict[tuple[str, str], datetime] = {}
    for key, record in _sent_notes(read_all(path=path)):
        if key not in latest or record.ts > latest[key]:
            latest[key] = record.ts
    return latest


def previous_texts(
    *, path: Path, note_id: str, list_name: str, limit: int
) -> list[str]:
    """The newest ``limit`` texts sent for one note, oldest first."""
    if limit < 1:
        # A slice of ``-0`` is the whole list, not an empty one.
        return []
    sent = sorted(
        (
            record
            for key, record in _sent_notes(read_all(path=path))
            if key == (list_name, note_id)
        ),
        key=lambda record: record.ts,
    )
    return [record.text for record in sent[-limit:]]
