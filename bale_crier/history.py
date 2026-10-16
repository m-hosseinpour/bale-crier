"""The history: append-only JSONL, one line per bulletin.

Appending is the whole write path, so a crash cannot lose the records already
written. The size cap is the one exception — when the file grows past it, the
newest lines are rewritten through a rename, never by truncating first.
"""

from datetime import datetime, timezone
from pathlib import Path

from .models import HistoryRecord


def _as_utc(ts: datetime) -> datetime:
    # A naive ts is read as UTC, never as the box's local time, so the file does
    # not shift when the machine's timezone changes.
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _last_byte(path: Path) -> bytes:
    if path.stat().st_size == 0:
        return b""
    with path.open("rb") as handle:
        handle.seek(-1, 2)
        return handle.read(1)


def append(record: HistoryRecord, *, path: Path, max_lines: int) -> None:
    # Checked before anything is written, so a bad cap cannot half-do its work.
    if max_lines < 1:
        raise ValueError(f"max_lines must be at least 1, got {max_lines}")
    path.parent.mkdir(parents=True, exist_ok=True)
    stored = record.model_copy(update={"ts": _as_utc(record.ts)})
    with path.open("a", encoding="utf-8") as handle:
        # A run killed mid-write leaves a fragment with no newline. Closing it off
        # first keeps it a line of its own, so the next record is not glued onto it
        # and lost along with it.
        if _last_byte(path) not in (b"", b"\n"):
            handle.write("\n")
        handle.write(stored.model_dump_json() + "\n")
    _trim(path=path, max_lines=max_lines)


def read_all(*, path: Path) -> list[HistoryRecord]:
    if not path.is_file():
        return []
    records: list[HistoryRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(HistoryRecord.model_validate_json(line))
        except ValueError:
            # A run killed mid-write leaves one broken line; the rest is intact.
            # pydantic's ValidationError is a ValueError, so one clause covers both.
            continue
    return records


def last_sent_at(*, note_id: str, list_name: str, path: Path) -> datetime | None:
    sent = [
        record.ts
        for record in read_all(path=path)
        if record.kind == "note"
        and record.ok
        and record.note_id == note_id
        and record.list_name == list_name
    ]
    return max(sent) if sent else None


def _trim(*, path: Path, max_lines: int) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) <= max_lines:
        return
    # Written to a neighbour and renamed: truncating the real file first would lose
    # the whole history to a crash mid-write, the one loss the append-only shape
    # exists to prevent.
    trimmed = path.with_name(f"{path.name}.tmp")
    trimmed.write_text(
        "".join(line + "\n" for line in lines[-max_lines:]), encoding="utf-8"
    )
    trimmed.replace(path)
