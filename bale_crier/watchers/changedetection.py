"""The changedetection watcher: one bulletin naming the pages that changed.

changedetection.io has already decided that a page changed; this watcher's job is
to remember which change the owner was last told about, and to speak once when a
watch's ``last_changed`` moves past that. The remembered numbers are the whole
state, so a run that sees nothing new says nothing and writes nothing.

One bulletin per run, not one per page: the pages are checked together and a run
rarely finds more than one, so a single message listing them is what the owner
reads in the morning rather than five buzzes in a row.

It also writes one thing back: once the message has landed, the pages it named are
marked viewed in changedetection, so their unread dot in the UI goes out (see `sent`).

A read that fails is a bulletin of its own, at most once every
``CRIER_CHANGEDETECTION_UNKNOWN_ALERT_HOURS``: "I cannot tell" is never announced
as "nothing changed", and it leaves the watermarks exactly as it found them, so a
change it could not see still speaks on the next run that can. A first read that
fails has no numbers to leave; the next successful run then takes the silent
baseline, which is the first-run rule applying to it too.
"""

from collections.abc import Callable
from datetime import datetime, timezone

from ..changedetection import (
    ADDED,
    CONTEXT,
    REMOVED,
    DiffRead,
    WatchesRead,
    epoch,
    fetch_diff,
    fetch_watches,
    mark_viewed,
)
from ..config import Settings
from ..memory import WatcherMemory
from ..bale import markdown_link
from ..models import Bulletin, Watch
from ..persian import digits
from .window import window_passed

WatchesReader = Callable[..., WatchesRead]
DiffReader = Callable[..., DiffRead]
Marker = Callable[..., str]

# Enough changed lines to see what happened, few enough that one runaway page (a
# whole feed, a JSON document) cannot bury the others.
DIFF_LINES = 10
# A single snapshot line can be a whole JSON object; a Bale message is one screen.
LINE_CHARS = 200
# Bale takes 4096 characters in one message, so the whole text is cut below that.
TEXT_CHARS = 3500
# Room kept for the "and N pages in the next message" line, so that notice can never
# push the text past the limit it is counting against.
NOTICE_CHARS = 64

# The label a page's link falls back to when changedetection has no title for it.
# A page is written with a title in the usual case; the API allows an empty one.
PAGE_LABEL = "صفحه"

UNKNOWN_TEXT = (
    "خواندن تغییر‌ها از changedetection ممکن نشد و نمی‌دانم چیزی عوض شده یا نه. "
    "این فقط یک خواندن ناموفق بود، نه خبری دربارهٔ بی‌تغییری."
)


def _ago(seconds: float) -> str:
    """How long before the run a change was seen, in words rather than a timestamp."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return "همین حالا"
    if seconds < 3600:
        return f"{digits(seconds // 60)} دقیقه پیش"
    if seconds < 86400:
        return f"{digits(seconds // 3600)} ساعت پیش"
    return f"{digits(seconds // 86400)} روز پیش"


def _heading(count: int) -> str:
    if count == 1:
        return "یک صفحه تغییر کرد:"
    return f"{digits(count)} صفحه تغییر کرد:"


def _clip_line(line: str) -> str:
    if len(line) <= LINE_CHARS:
        return line
    return f"{line[: LINE_CHARS - 1]}…"


def _kept(lines: list[str]) -> list[int]:
    """The indexes of at most ``DIFF_LINES`` lines, shared between both directions.

    changedetection renders a rewritten line as all of its old lines and then all of
    its new ones, so the first ten lines of a big change are ten ``-`` and not one
    ``+``: the owner would read ten things vanishing and never see the replacements.
    Each direction gets half the budget and the short side lends the rest; context lines
    carry no direction, so they only fill what the two sides leave.
    """
    if len(lines) <= DIFF_LINES:
        return list(range(len(lines)))
    removed = [index for index, line in enumerate(lines) if line.startswith(REMOVED)]
    added = [index for index, line in enumerate(lines) if line.startswith(ADDED)]
    take_removed = min(len(removed), DIFF_LINES // 2)
    take_added = min(len(added), DIFF_LINES - take_removed)
    # A side with fewer lines than its half lends the rest of the budget to the other.
    take_removed = min(len(removed), DIFF_LINES - take_added)
    kept = removed[:take_removed] + added[:take_added]
    room = DIFF_LINES - len(kept)
    if room:
        context = [index for index, line in enumerate(lines) if line.startswith(CONTEXT)]
        kept += context[:room]
    return sorted(kept)


def _block(watch: Watch, diff: DiffRead, now: datetime) -> str:
    ago = _ago(now.timestamp() - watch.last_changed)
    # The page's own title is the link's label, so the address rides under it instead
    # of taking the line: a watch's URL is often long, and it is the same page the
    # title already names.
    head = f"{markdown_link(watch.title, watch.url, fallback=PAGE_LABEL)} — {ago}"
    if diff.lines is None:
        return f"{head}\nمتن تغییر خوانده نشد: {diff.error}"
    if not diff.lines:
        # A watch with a single snapshot has nothing to diff against: the change is
        # real — `last_changed` proved it — and only the text is absent.
        return f"{head}\nمتن تغییر در دسترس نیست."
    kept = _kept(diff.lines)
    lines = [_clip_line(diff.lines[index]) for index in kept]
    if len(kept) < len(diff.lines):
        lines.append(f"… و {digits(len(diff.lines) - len(kept))} خط دیگر.")
    return "\n".join([head, *lines])


def _text(blocks: list[str]) -> tuple[str, list[int]]:
    """The message, and the indexes of the blocks it actually carries.

    The first block is clipped until it fits, so a run always names a page and always
    makes progress; the rest are taken whole while they fit, and the count of what was
    left over goes in the last line — which is a promise the run keeps, by leaving those
    pages' watermarks where they were.
    """
    heading = _heading(len(blocks))
    room = TEXT_CHARS - len(heading) - 2 - NOTICE_CHARS
    limit = TEXT_CHARS - NOTICE_CHARS
    text = heading
    carried: list[int] = []
    for index, block in enumerate(blocks):
        if not carried and len(block) > room:
            block = f"{block[: room - 1]}…"
        elif len(text) + 2 + len(block) > limit:
            # A smaller block further down may still fit; skipping this one is what
            # keeps the room from being wasted on the first page that happens to be big.
            continue
        text = f"{text}\n\n{block}"
        carried.append(index)
    dropped = len(blocks) - len(carried)
    if dropped:
        text = f"{text}\n\n… و {digits(dropped)} صفحهٔ دیگر، در پیام بعدی."
    return text, carried


class ChangedetectionWatcher:
    name = "changedetection"
    own_timer = True

    def __init__(
        self,
        settings: Settings,
        memory: WatcherMemory,
        read: WatchesReader = fetch_watches,
        read_diff: DiffReader = fetch_diff,
        mark: Marker = mark_viewed,
    ) -> None:
        self._settings = settings
        self._memory = memory
        self._read = read
        self._read_diff = read_diff
        self._mark = mark
        # What this run told the owner about, for `sent` to clear the dots of.
        self._reported: list[Watch] = []

    def produce(self, now: datetime) -> list[Bulletin]:
        now = now.astimezone(timezone.utc)
        # A run that says nothing — a failure, a baseline, a quiet tick — marks nothing.
        self._reported = []
        read = self._read(
            base_url=self._settings.changedetection_url,
            key=self._settings.changedetection_api_key or "",
            timeout=self._settings.http_timeout,
        )
        if read.watches is None:
            return self._unreadable(now, read.error)

        seen = self._memory.get(self.name).get("seen")
        if not isinstance(seen, dict):
            # The first run ever. Everything under watch changed at some point, and
            # none of it is news: the numbers are recorded and nothing is said.
            self._remember(seen=self._watermarks(read.watches))
            return []

        changed = [
            watch
            for watch in read.watches
            if watch.uuid in seen and watch.last_changed > epoch(seen[watch.uuid])
        ]
        if not changed:
            # A quiet run still records what it learned — a watch added since the last
            # one, a history cleared in the UI — and says nothing.
            self._remember(seen=self._watermarks(read.watches))
            return []

        # Oldest first, so a page can never wait behind the ones that changed after it:
        # the page left over is the newest, and it is first next run. It also reads in
        # the order things happened.
        changed.sort(key=lambda watch: watch.last_changed)
        text, carried = _text([self._diff_block(watch, now) for watch in changed])

        # The watermarks the message carries are recorded; a page whose block did not
        # fit keeps its old number, so the next run carries it — which is what the last
        # line of the message promises.
        watermarks = self._watermarks(read.watches)
        for index, watch in enumerate(changed):
            if index not in carried:
                watermarks[watch.uuid] = epoch(seen[watch.uuid])
        self._remember(seen=watermarks)
        self._reported = [changed[index] for index in carried]
        return [Bulletin(kind="watch", text=text)]

    def sent(self, *, ok: bool, now: datetime) -> None:
        """Clear the unread dot of the pages this run told the owner about.

        Only after a send that landed: a failed send repeats on the next run, and the dot
        is the UI's record of "Bale has not told me yet", so it must not go out early.
        A mark that fails is not retried and not mentioned in the message — the dot
        staying is the safe direction, and the message itself has already gone.
        """
        reported, self._reported = self._reported, []
        if not ok:
            return
        for watch in reported:
            self._mark(
                base_url=self._settings.changedetection_url,
                key=self._settings.changedetection_api_key or "",
                uuid=watch.uuid,
                # A clock behind the snapshot's would leave the dot on: "now" is what
                # marks it viewed, but never less than the change it is marking.
                at=max(int(now.timestamp()), watch.last_changed),
                timeout=self._settings.http_timeout,
            )

    def _diff_block(self, watch: Watch, now: datetime) -> str:
        diff = self._read_diff(
            base_url=self._settings.changedetection_url,
            key=self._settings.changedetection_api_key or "",
            uuid=watch.uuid,
            timeout=self._settings.http_timeout,
        )
        return _block(watch, diff, now)

    def _watermarks(self, watches: list[Watch]) -> dict[str, int]:
        # A watch seen for the first time is recorded silently: its last change may be
        # from before the watch was added, and reporting it now would be a message
        # about something the owner never asked to be told about.
        return {watch.uuid: watch.last_changed for watch in watches}

    def _unreadable(self, now: datetime, error: str) -> list[Bulletin]:
        state = self._memory.get(self.name)
        if not window_passed(
            state.get("last_unknown_alert"),
            now=now,
            hours=self._settings.changedetection_unknown_alert_hours,
        ):
            return []
        # The watermarks are carried over untouched: a failed read must not consume
        # the change it could not see.
        self._remember(unknown_at=now)
        text = f"{UNKNOWN_TEXT}\n\n{error}" if error else UNKNOWN_TEXT
        return [Bulletin(kind="alert", text=text)]

    def _remember(
        self,
        *,
        seen: dict[str, int] | None = None,
        unknown_at: datetime | None = None,
    ) -> None:
        state = self._memory.get(self.name)
        written = {
            "seen": state.get("seen") if seen is None else seen,
            "last_unknown_alert": (
                unknown_at.isoformat() if unknown_at is not None else state.get("last_unknown_alert")
            ),
        }
        # A run that learned nothing new leaves the file alone, so a quiet run is
        # invisible on disk as well as in the chat.
        if written != state:
            self._memory.set(self.name, written)
