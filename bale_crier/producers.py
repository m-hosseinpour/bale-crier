"""Producers: what a run asks for bulletins right now.

A producer is one kind of message. The smoke producer lives here; the ones that
need settings or a memory to write to — the credit watcher today, the note-list
reader later — are built in ``run.build_producers``.
"""

from datetime import datetime
from typing import Protocol

from .models import Bulletin


class Producer(Protocol):
    name: str
    # A producer that runs on a timer of its own sets this, and the daily run
    # leaves it out — two timers must not race over one latch.
    own_timer: bool = False

    def produce(self, now: datetime) -> list[Bulletin]: ...


class SmokeProducer:
    """One fixed test bulletin, so the path can be proved after a deploy."""

    name = "smoke"
    own_timer = False

    def produce(self, now: datetime) -> list[Bulletin]:
        return [
            Bulletin(
                kind="smoke",
                text="این یک پیام آزمایشی از ربات bale_crier است. اگر آن را می‌بینید، مسیر ارسال تا بله سالم است.",
            )
        ]
