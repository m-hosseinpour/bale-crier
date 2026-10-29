"""One run: ask the producers, send every bulletin, record every outcome."""

from collections.abc import Callable, Sequence
from datetime import datetime

from .bale import send_message
from .config import Settings
from .history import append
from .memory import WatcherMemory
from .models import HistoryRecord, RunReport, SendResult
from .news.producer import NewsProducer
from .notes.producer import NoteProducer
from .producers import Producer, SmokeProducer
from .watchers.avalai_credit import CreditWatcher
from .watchers.changedetection import ChangedetectionWatcher
from .watchers.disk import DiskWatcher

Sender = Callable[..., SendResult]

SMOKE = SmokeProducer.name
CREDIT = CreditWatcher.name
DISK = DiskWatcher.name
CHANGEDETECTION = ChangedetectionWatcher.name
NOTE = NoteProducer.name
NEWS = NewsProducer.name

# Every name `--only` may name, whether or not this run can build it.
KNOWN_PRODUCERS = (SMOKE, CREDIT, DISK, CHANGEDETECTION, NOTE, NEWS)

# A sender that failed without a word — an empty `error` — still gets a line in the
# journal, and an empty one there would read as a bug in the reporting.
NO_REASON = "بدون توضیح"


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
    # The disk needs no key and no network, so it is always registered.
    available[DiskWatcher.name] = DiskWatcher(settings, memory)
    # Without the API key changedetection refuses every read, so the watcher is not
    # registered at all rather than registering one that can only fail.
    if settings.changedetection_api_key:
        available[ChangedetectionWatcher.name] = ChangedetectionWatcher(settings, memory)
    # Same for the two that need the model: no key, no rewording and no digest.
    # The digest's feed is fetched at produce time, so an unreachable feed is not
    # a reason to leave it out.
    if settings.open_ai_api_key:
        available[NoteProducer.name] = NoteProducer(settings)
        available[NewsProducer.name] = NewsProducer(settings, memory)

    if only is not None:
        unknown = [name for name in only if name not in KNOWN_PRODUCERS]
        if unknown:
            raise ValueError(f"unknown producer name: {', '.join(unknown)}")
        return [available[name] for name in only if name in available]

    if settings.smoke:
        # The smoke producer is the deploy check, and it stays one fixed message: a
        # run that is proving the path must not also spend a note on the owner.
        return [available[SmokeProducer.name]]

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

    sent = 0
    failed = 0
    errors: list[str] = []
    for producer in producers:
        # Per producer, because one that also writes back — today only the
        # changedetection watcher, which clears the pages' unread dots — must learn
        # whether *its* bulletin landed, not how the run as a whole went.
        landed = True
        for bulletin in producer.produce(now):
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
                errors.append(result.error or NO_REASON)
            landed = landed and result.ok
            # Written for a failed send too: a silent failure is the one outcome the
            # owner cannot debug afterwards.
            append(
                HistoryRecord(
                    ts=now,
                    kind=bulletin.kind,
                    text=bulletin.text,
                    list_name=bulletin.list_name,
                    note_id=bulletin.note_id,
                    ok=result.ok,
                    error=result.error,
                ),
                path=settings.history_path,
                max_lines=settings.history_max_lines,
            )
        # A producer that must know how its bulletin went says so by having this
        # method; the ones that do not are told nothing and need nothing.
        notify = getattr(producer, "sent", None)
        if notify is not None:
            notify(ok=landed, now=now)

    # Saved only when every send landed: a failed send must cost a repeat next run,
    # never the change it was carrying. A crash between produce and send already left
    # the memory unsaved for the same reason.
    if not failed:
        memory.save()

    return RunReport(
        sent=sent,
        failed=failed,
        producers=[producer.name for producer in producers],
        errors=errors,
    )
