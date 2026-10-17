"""The shapes the crier passes around.

Every milestone adds the models it owns here, so the whole data model reads in
one file.
"""

from datetime import datetime

from pydantic import BaseModel


class Package(BaseModel):
    """One credit pot the provider lists: a daily, weekly or unclassified package."""

    tier: str
    name: str
    remaining_irt: float | None
    amount_irt: float | None
    end_date: datetime | None
    spendable: bool


class CreditReport(BaseModel):
    """The credit endpoint, parsed into numbers.

    ``active_remaining_irt`` is the number the threshold watches: the active
    tier's spendable balance, or the main balance when no package is live. It is
    ``None`` when neither could be read — a failure, never a zero balance.
    """

    main_balance_irt: float | None
    packages: list[Package]
    tier_remaining: dict[str, float]
    active_tier: str | None
    active_remaining_irt: float | None


class SendResult(BaseModel):
    """The outcome of one call to Bale. A failure is a value, never an exception."""

    ok: bool
    error: str | None = None


class Note(BaseModel):
    """One item in one of the owner's lists: a ``## id`` heading plus its body."""

    list_name: str
    id: str
    text: str


class Story(BaseModel):
    """One entry in the news feed: a headline, its source and its link.

    ``published`` is timezone-aware UTC whenever the feed gave a date, and
    ``None`` when it did not — a story without a date is still a story.
    """

    title: str
    source: str
    link: str
    guid: str
    published: datetime | None


class Bulletin(BaseModel):
    """One message that goes to Bale. Kinds so far: ``smoke``, ``alert``, ``note``, ``news``."""

    kind: str
    text: str
    note_id: str | None = None
    list_name: str | None = None


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
