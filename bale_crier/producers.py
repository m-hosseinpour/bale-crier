"""Producers: what a run asks for bulletins right now.

A producer is one kind of message. Milestone 1 has the smoke producer alone;
the AvalAI credit watcher and the note-list reader register here later.
"""

from datetime import datetime
from typing import Protocol

from .models import Bulletin


class Producer(Protocol):
    name: str

    def produce(self, now: datetime) -> list[Bulletin]: ...


class SmokeProducer:
    """One fixed test bulletin, so the path can be proved after a deploy."""

    name = "smoke"

    def produce(self, now: datetime) -> list[Bulletin]:
        return [
            Bulletin(
                kind="smoke",
                text="این یک پیام آزمایشی از ربات bale_crier است. اگر آن را می‌بینید، مسیر ارسال تا بله سالم است.",
            )
        ]
