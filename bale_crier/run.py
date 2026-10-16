"""One run: ask the producers, send every bulletin, record every outcome."""

from collections.abc import Callable, Sequence
from datetime import datetime

from .bale import send_message
from .config import Settings
from .history import append
from .memory import WatcherMemory
from .models import HistoryRecord, RunReport, SendResult
from .producers import Producer, SmokeProducer
from .watchers.avalai_credit import CreditWatcher

Sender = Callable[..., SendResult]

# Every name `--only` may name, whether or not this run can build it.
KNOWN_PRODUCERS = (SmokeProducer.name, CreditWatcher.name)


def build_producers(
    settings: Settings,
    *,
    memory: WatcherMemory,
    only: Sequence[str] | None = None,
) -> list[Producer]:
    available: dict[str, Producer] = {}
    if settings.smoke:
        available[SmokeProducer.name] = SmokeProducer()
    # No key means the watcher cannot read anything, so it is not registered.
    if settings.avalai_api_key:
        available[CreditWatcher.name] = CreditWatcher(settings, memory)

    if only is not None:
        unknown = [name for name in only if name not in KNOWN_PRODUCERS]
        if unknown:
            raise ValueError(f"unknown producer name: {', '.join(unknown)}")
        return [available[name] for name in only if name in available]

    return [producer for producer in available.values() if not producer.own_timer]


def run_once(
    settings: Settings,
    *,
    now: datetime,
    send: Sender = send_message,
    only: Sequence[str] | None = None,
) -> RunReport:
    memory = WatcherMemory.load(settings.watchers_state_path)
    producers = build_producers(settings, memory=memory, only=only)
    bulletins = [bulletin for producer in producers for bulletin in producer.produce(now)]

    sent = 0
    failed = 0
    for bulletin in bulletins:
        result = send(
            bulletin.text,
            token=settings.bale_bot_token,
            chat_id=settings.bale_chat_id,
            timeout=settings.http_timeout,
        )
        if result.ok:
            sent += 1
        else:
            failed += 1
        # Written for a failed send too: a silent failure is the one outcome the
        # owner cannot debug afterwards.
        append(
            HistoryRecord(
                ts=now,
                kind=bulletin.kind,
                text=bulletin.text,
                note_id=bulletin.note_id,
                ok=result.ok,
            ),
            path=settings.history_path,
            max_lines=settings.history_max_lines,
        )

    # Saved after the sends, so a crash between the two re-alerts next run — the
    # safe direction.
    memory.save()

    return RunReport(sent=sent, failed=failed, producers=[producer.name for producer in producers])
