"""One run: ask the producers, send every bulletin, record every outcome."""

from collections.abc import Callable
from datetime import datetime

from .bale import send_message
from .config import Settings
from .history import append
from .models import HistoryRecord, RunReport, SendResult
from .producers import Producer, SmokeProducer

Sender = Callable[..., SendResult]


def build_producers(settings: Settings) -> list[Producer]:
    return [SmokeProducer()] if settings.smoke else []


def run_once(settings: Settings, *, now: datetime, send: Sender = send_message) -> RunReport:
    producers = build_producers(settings)
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

    return RunReport(sent=sent, failed=failed, producers=[producer.name for producer in producers])
