"""The news digest: the feed, filtered, reworded by the LLM, one bulletin.

The producer orchestrates and the modules around it own their parts: ``feed``
fetches and parses, ``select`` filters, prompts, parses the answer and words every
message, and this only decides the order of those steps and what to remember.

The seen set is this producer's own memory, keyed by guid, so it is the producer
that reads and writes it — and the run loop that saves it, after the sends.
"""

from datetime import datetime

from ..config import Settings
from ..llm import Llm, complete
from ..memory import WatcherMemory
from ..models import Bulletin
from .feed import FeedReader, fetch_feed
from .select import (
    CANDIDATE_LIMIT,
    blocklist_words,
    blocked,
    build_messages,
    digest_text,
    feed_failure_text,
    newest_first,
    parse_answer,
    raw_text,
    remember,
    seen_guids,
)


class NewsProducer:
    name = "news"
    # The digest runs on its own timer, so the daily note run leaves it out and
    # the two cannot race over one seen set.
    own_timer = True

    def __init__(
        self,
        settings: Settings,
        memory: WatcherMemory,
        *,
        complete: Llm = complete,
        read: FeedReader = fetch_feed,
    ) -> None:
        self._settings = settings
        self._memory = memory
        self._complete = complete
        self._read = read

    def produce(self, now: datetime) -> list[Bulletin]:
        """Zero or one bulletin. ``now`` is the protocol's, not this producer's.

        The seen set is keyed by guid, so nothing here depends on the clock; the
        parameter stays because every producer takes it.
        """
        read = self._read(url=self._settings.news_feed_url, timeout=self._settings.http_timeout)
        if read.stories is None:
            # A read that failed is never a quiet day, and it costs no model call
            # and no memory write: nothing was chosen, so nothing is remembered.
            return [Bulletin(kind=self.name, text=feed_failure_text(read.error))]

        words = blocklist_words(self._settings.news_blocklist)
        seen = seen_guids(self._memory.get(self.name))
        known = set(seen)
        survivors = [
            story
            for story in read.stories
            if not blocked(story.title, words) and story.guid not in known
        ]
        if not survivors:
            return []

        candidates = newest_first(survivors)[:CANDIDATE_LIMIT]
        max_items = self._settings.news_max_items
        llm_read = self._complete(
            build_messages(candidates, max_items=max_items),
            key=self._settings.open_ai_api_key or "",
            model=self._settings.open_ai_model,
            base_url=self._settings.open_ai_base_url,
            timeout=self._settings.http_timeout,
        )

        chosen = None
        if llm_read.text is not None:
            chosen = parse_answer(llm_read.text, candidates, max_items=max_items)

        if chosen is not None:
            carried = [item.story for item in chosen]
            text = digest_text(chosen)
        else:
            # The model's failure is the owner's English fallback: the newest
            # survivors go out as they came, capped here because the cap is the
            # settings' business and `raw_text` renders only what it is given.
            carried = candidates[:max_items]
            error = llm_read.error if llm_read.text is None else "unparsable answer"
            text = raw_text(carried, error)

        self._memory.set(self.name, {"seen": remember(seen, [story.guid for story in carried])})
        return [Bulletin(kind=self.name, text=text)]
