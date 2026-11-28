"""The note producer: the owner's lists, one note per run.

Read the list directory, ask the history which note the cycle makes due, and hand
back one bulletin carrying the note's own text. With ``CRIER_NOTE_REWORD`` on, the
model expands the note into fresh Persian first; a reword that fails still sends
the note's own text, so a model that is down costs the owner wording, not the note.
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
    # The notes are the ordinary run's own work; only a producer that owns a timer of
    # its own (the three watchers and the news digest) is left out of that run.
    own_timer = False

    def __init__(self, settings: Settings, *, complete: Llm = complete) -> None:
        self._settings = settings
        self._complete = complete
        # The switch is the owner's, and a reword also needs the key: without one the
        # call could only fail, so the note goes out as it is and the CLI says why.
        self._use_model = settings.note_reword and bool(settings.open_ai_api_key)

    def produce(self, now: datetime) -> list[Bulletin]:
        chosen = choose_note(
            read_notes(self._settings.lists_dir),
            last_sent=last_sent_map(path=self._settings.history_path),
        )
        if chosen is None:
            return []
        text = chosen.text
        if self._use_model:
            # The wordings this note already arrived in, so the model can avoid them.
            previous = previous_texts(
                path=self._settings.history_path,
                note_id=chosen.id,
                list_name=chosen.list_name,
                limit=PREVIOUS_LIMIT,
            )
            text = reword(
                chosen,
                previous,
                settings=self._settings,
                complete=self._complete,
            )
        return [
            Bulletin(
                kind="note",
                text=text,
                note_id=chosen.id,
                list_name=chosen.list_name,
            )
        ]
