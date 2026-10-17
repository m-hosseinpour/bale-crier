"""Reading the owner's lists into notes.

A list is one Markdown file; a note is a ``## id`` heading and the body under it.
The files are read fresh on every run and written nowhere — they are the owner's.
"""

from pathlib import Path

from ..models import Note


def read_notes(directory: Path) -> list[Note]:
    """Every note in the directory's Markdown files, in file-name order."""
    if not directory.is_dir():
        return []
    notes: list[Note] = []
    for path in sorted(directory.glob("*.md")):
        notes.extend(_read_file(path))
    return notes


def _read_file(path: Path) -> list[Note]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # One unreadable file costs only its own notes, never the other files'.
        return []
    return _parse(text, list_name=path.stem)


def _heading_id(line: str) -> str | None:
    # Deliberately loose — ``##`` plus any whitespace — so a two-word id is not
    # read as a plain line and silently folded into the previous note's body.
    if not line.startswith("##") or len(line) < 3 or not line[2].isspace():
        return None
    return line[2:].strip()


def _parse(text: str, *, list_name: str) -> list[Note]:
    notes: list[Note] = []
    seen: set[str] = set()
    heading: str | None = None
    body: list[str] = []

    def close() -> None:
        if heading is None:
            return
        stripped = "\n".join(body).strip()
        # An empty body has nothing to reword, and a repeated id is the same note
        # as the first one: neither becomes a note of its own.
        if stripped and heading not in seen:
            seen.add(heading)
            notes.append(Note(list_name=list_name, id=heading, text=stripped))

    for line in text.splitlines():
        found = _heading_id(line)
        if found is not None:
            close()
            heading = found
            body = []
        elif heading is not None:
            body.append(line)
    close()
    return notes
