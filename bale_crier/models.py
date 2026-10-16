"""The shapes the crier passes around.

Every milestone adds the models it owns here, so the whole data model reads in
one file.
"""

from datetime import datetime

from pydantic import BaseModel


class SendResult(BaseModel):
    """The outcome of one call to Bale. A failure is a value, never an exception."""

    ok: bool
    error: str | None = None


class Bulletin(BaseModel):
    """One message that goes to Bale. Kinds so far: ``smoke``, ``alert``, ``note``."""

    kind: str
    text: str
    note_id: str | None = None


class HistoryRecord(BaseModel):
    """One line of the history: one bulletin that was sent, and how it went."""

    ts: datetime
    kind: str
    text: str
    list_name: str | None = None
    note_id: str | None = None
    ok: bool


class RunReport(BaseModel):
    """What one run did, for the summary line and the exit code."""

    sent: int
    failed: int
    producers: list[str]
