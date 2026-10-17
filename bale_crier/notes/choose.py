"""Choosing which note is due: the cycle.

The cycle puts the note whose last send is oldest first, so every note is reached
before any repeats, and a note that has never gone is the oldest send of all.

There is deliberately no repeat floor. With the notes ordered by last send, the
notes outside a "not within N days" window are always a prefix of that ordering,
so such a filter hands back the note the cycle already picked — and when every
note is inside the window, the small-list fallback hands back that same note.
Measured 2026-10-17: deleting the filter leaves every test green, which is what a
rule that changes no answer looks like.

The last-send times are passed in, so the choice reads no files and writes none.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime

from ..history import as_utc
from ..models import Note


def choose_note(
    notes: Sequence[Note],
    *,
    last_sent: Mapping[tuple[str, str], datetime],
) -> Note | None:
    """The note the cycle makes due, or ``None`` when there are none."""
    if not notes:
        return None
    sent_at = {
        (note.list_name, note.id): as_utc(last_sent[(note.list_name, note.id)])
        for note in notes
        if (note.list_name, note.id) in last_sent
    }

    # A never-sent note is the oldest possible send, so the cycle puts it first;
    # among several, the first in input order keeps a run deterministic.
    unsent = [note for note in notes if (note.list_name, note.id) not in sent_at]
    if unsent:
        return unsent[0]

    # ``min`` keeps the first of equal keys, so a tie is the input order again.
    return min(notes, key=lambda note: sent_at[(note.list_name, note.id)])
