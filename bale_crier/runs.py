"""The run log: append-only JSONL, one line per completed run.

The history records what the owner read; this records what the process did. A
quiet run — nothing to send, or no producer it could build — still writes a line,
so a long silence in Bale can be read as "the timer ran and had nothing to say"
instead of "the timer died".
"""

from pathlib import Path

from .history import as_utc
from .jsonl import append_line, read_lines
from .models import RunRecord


def append(record: RunRecord, *, path: Path, max_lines: int) -> None:
    stored = record.model_copy(update={"ts": as_utc(record.ts)})
    append_line(stored.model_dump_json(), path=path, max_lines=max_lines)


def read_all(*, path: Path) -> list[RunRecord]:
    records: list[RunRecord] = []
    for line in read_lines(path=path):
        if not line.strip():
            continue
        try:
            records.append(RunRecord.model_validate_json(line))
        except ValueError:
            # A run killed mid-write leaves one broken line; the rest is intact.
            continue
    return records
