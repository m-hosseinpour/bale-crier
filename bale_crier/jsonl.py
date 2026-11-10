"""An append-only JSONL file with a size cap: the shape the history and the run
log share.

Appending is the whole write path, so a crash cannot lose the lines already
written. The size cap is the one exception — when the file grows past it, the
newest lines are rewritten through a rename, never by truncating first.
"""

from pathlib import Path


def _last_byte(path: Path) -> bytes:
    if path.stat().st_size == 0:
        return b""
    with path.open("rb") as handle:
        handle.seek(-1, 2)
        return handle.read(1)


def append_line(line: str, *, path: Path, max_lines: int) -> None:
    # Checked before anything is written, so a bad cap cannot half-do its work.
    if max_lines < 1:
        raise ValueError(f"max_lines must be at least 1, got {max_lines}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        # A run killed mid-write leaves a fragment with no newline. Closing it off
        # first keeps it a line of its own, so the next record is not glued onto it
        # and lost along with it.
        if _last_byte(path) not in (b"", b"\n"):
            handle.write("\n")
        handle.write(line + "\n")
    _trim(path=path, max_lines=max_lines)


def read_lines(*, path: Path) -> list[str]:
    if not path.is_file():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def _trim(*, path: Path, max_lines: int) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) <= max_lines:
        return
    # Written to a neighbour and renamed: truncating the real file first would lose
    # the whole file to a crash mid-write, the one loss the append-only shape exists
    # to prevent.
    trimmed = path.with_name(f"{path.name}.tmp")
    trimmed.write_text(
        "".join(line + "\n" for line in lines[-max_lines:]), encoding="utf-8"
    )
    trimmed.replace(path)
