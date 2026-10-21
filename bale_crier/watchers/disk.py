"""The disk watcher: free space with a latch and a daily reminder.

Below the threshold while the latch is armed speaks once; above it the latch
re-arms. While space stays below, the owner gets a reminder at most once every
``CRIER_DISK_REMINDER_HOURS``: a disk that is not cleaned up does not fix itself,
so one crossing alert alone would scroll away and be forgotten.

A read that fails is its own bulletin — "I cannot tell" is never "the disk is
full" — and it leaves the latch exactly as it found it.
"""

import shutil
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from math import floor
from pathlib import Path

from ..config import Settings
from ..memory import WatcherMemory
from ..models import Bulletin

DiskReader = Callable[[Path], int]

GIB = 1024**3

UNKNOWN_TEXT = (
    "خواندن فضای دیسک ممکن نشد و نمی‌دانم چقدر خالی مانده است. "
    "این فقط یک خواندن ناموفق بود، نه خبری دربارهٔ پر بودن دیسک."
)


def free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def _gib(value: float, *, down: bool = False) -> str:
    # Free space is floored: rounding 1.999 up to "2" would print the threshold
    # back at the owner as if nothing were wrong.
    scaled = value / GIB
    if down:
        scaled = floor(scaled * 100) / 100
    return f"{scaled:.2f}".rstrip("0").rstrip(".")


class DiskWatcher:
    name = "disk"
    own_timer = True

    def __init__(
        self,
        settings: Settings,
        memory: WatcherMemory,
        read: DiskReader = free_bytes,
    ) -> None:
        self._settings = settings
        self._memory = memory
        self._read = read

    def produce(self, now: datetime) -> list[Bulletin]:
        now = now.astimezone(timezone.utc)
        try:
            free = self._read(self._settings.disk_path)
        except OSError as error:
            return self._unreadable(now, str(error))

        if free >= self._settings.disk_threshold_gib * GIB:
            self._arm()
            return []

        state = self._memory.get(self.name)
        if state.get("armed", True):
            self._remember(armed=False, at=now)
            return [self._alert(free, crossed=True)]

        if not self._window_passed(state.get("last_alert"), now):
            return []
        self._remember(armed=False, at=now)
        return [self._alert(free, crossed=False)]

    def _alert(self, free: int, *, crossed: bool) -> Bulletin:
        threshold = _gib(self._settings.disk_threshold_gib * GIB)
        opening = (
            "فضای آزاد دیسک از آستانه پایین‌تر آمد"
            if crossed
            else "فضای آزاد دیسک هنوز پایین‌تر از آستانه است"
        )
        return Bulletin(
            kind="alert",
            text=(
                f"{opening}: {_gib(free, down=True)} گیگابایت خالی مانده "
                f"و آستانه {threshold} گیگابایت است."
            ),
        )

    def _unreadable(self, now: datetime, error: str) -> list[Bulletin]:
        state = self._memory.get(self.name)
        if not self._window_passed(state.get("last_alert"), now):
            return []
        # The latch is carried over untouched: a failed read must not consume the
        # crossing it could not see, nor re-arm one that was already set.
        self._remember(armed=state.get("armed", True), at=now)
        text = f"{UNKNOWN_TEXT}\n\n{error}" if error else UNKNOWN_TEXT
        return [Bulletin(kind="alert", text=text)]

    def _arm(self) -> None:
        if not self._memory.get(self.name).get("armed", True):
            self._remember(armed=True)

    def _window_passed(self, last: object, now: datetime) -> bool:
        if not last:
            return True
        try:
            previous = datetime.fromisoformat(str(last))
            return now - previous >= timedelta(hours=self._settings.disk_reminder_hours)
        except (ValueError, TypeError):
            # A corrupt or naive timestamp costs one extra bulletin, never a crash.
            return True

    def _remember(self, *, armed: bool, at: datetime | None = None) -> None:
        state = self._memory.get(self.name)
        self._memory.set(
            self.name,
            {
                "armed": armed,
                "last_alert": (
                    at.isoformat() if at is not None else state.get("last_alert")
                ),
            },
        )
