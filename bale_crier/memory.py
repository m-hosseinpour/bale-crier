"""A watcher's own state, kept across runs.

Deliberately not the history: the history records what the owner read, and
nothing else. This file holds one JSON object per producer name; its contents are
the producer's own business, and the store only loads, hands out and saves it.

A run saves only the names it actually changed, merged into whatever is on disk at
that moment. That is what stops the daily run — which registers no credit watcher
but shares this file — from writing back the copy it loaded and undoing a latch the
hourly run re-armed in between, which would silently swallow the next crossing.

Two runs writing the *same* name at once would still need a lock, and there is
none: a producer that owns a timer is the only run that writes its own name.

The write goes through a neighbour file and a rename: a crash mid-write must not
leave a half-written file that then reads as "no memory", which would re-alert.
"""

import json
from pathlib import Path


def _read(path: Path) -> dict[str, dict]:
    """Whatever is on disk, or an empty mapping. Never raises."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # A corrupt or unreadable memory costs an extra alert, never a crash.
        return {}
    if not isinstance(raw, dict):
        return {}
    return {name: value for name, value in raw.items() if isinstance(value, dict)}


class WatcherMemory:
    def __init__(self, *, path: Path, data: dict[str, dict] | None = None) -> None:
        self._path = path
        self._data = dict(data) if data else {}
        self._dirty: set[str] = set()

    @classmethod
    def load(cls, path: Path) -> "WatcherMemory":
        return cls(path=path, data=_read(path))

    def get(self, name: str) -> dict:
        return dict(self._data.get(name, {}))

    def set(self, name: str, value: dict) -> None:
        self._data[name] = value
        self._dirty.add(name)

    def as_dict(self) -> dict[str, dict]:
        return dict(self._data)

    def save(self) -> None:
        if not self._dirty:
            # Nothing was written this run: leave the file exactly as it is, so a
            # run that changed nothing is invisible on disk as well as in the chat.
            return
        # Re-read now and merge only this run's names: another run may have written
        # a different name since this one loaded, and a whole-file write would undo
        # it without a word.
        merged = _read(self._path)
        merged.update({name: self._data[name] for name in self._dirty})
        self._path.parent.mkdir(parents=True, exist_ok=True)
        neighbour = self._path.with_name(f"{self._path.name}.tmp")
        neighbour.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
        neighbour.replace(self._path)
        self._data = merged
        self._dirty.clear()
