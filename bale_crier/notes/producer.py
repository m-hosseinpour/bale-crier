"""The note producer: the owner's lists, one note per run.

Read the list directory, ask the history which note the cycle makes due, have the
LLM reword it, and hand back one bulletin. A reword that fails still sends the
note's own text, so a model that is down costs the owner wording, not the note.
"""

from datetime import datetime

from ..config import Settings
from ..history import last_sent_map, previous_texts
from ..llm import Llm, complete
from ..models import Bulletin
from .choose import choose_note
from .lists import read_notes
from .reword import PREVIOUS_LIMIT, reword


class NoteProducer:
    name = "note"
    # The notes are the daily run's own work; only a producer that owns a timer of
    # its own (the credit watcher) is left out of that run.
    own_timer = False

    def __init__(self, settings: Settings, *, complete: Llm = complete) -> None:
        self._settings = settings
        self._complete = complete

    def produce(self, now: datetime) -> list[Bulletin]:
        chosen = choose_note(
            read_notes(self._settings.lists_dir),
            last_sent=last_sent_map(path=self._settings.history_path),
        )
        if chosen is None:
            return []
        # The wordings this note already arrived in, so the model can avoid them.
        previous = previous_texts(
            path=self._settings.history_path,
            note_id=chosen.id,
            list_name=chosen.list_name,
            limit=PREVIOUS_LIMIT,
        )
        return [
            Bulletin(
                kind="note",
                text=reword(
                    chosen,
                    previous,
                    settings=self._settings,
                    complete=self._complete,
                ),
                note_id=chosen.id,
                list_name=chosen.list_name,
            )
        ]
