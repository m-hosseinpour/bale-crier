"""Choosing the digest's stories, prompting for them, and wording the message.

The hard filter and the seen set run before the model, so it never sees a story
the owner asked to be spared or one already carried. The model answers with
indices, never links, so a model that invents a link is impossible: the code maps
each index back to the real story.

The failure rule is read literally: one unparsable line, one out-of-range index, or
an answer with no usable line at all fails the whole answer rather than dropping
the bad line. That is the one place the digest prefers the English fallback over a
partial digest.

The message text lives here, not in the producer, for the same reason the note's
fallback lives in ``notes/reword.py``: the producer orchestrates, and the module
that shapes the content owns its words.

The Persian constants spell every half-space as ``\u200c`` on purpose: the
generating model drops the character in several of these words, and an explicit
escape is the one way to be sure it is there.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import NamedTuple

from ..models import Story

DEFAULT_BLOCKLIST: tuple[str, ...] = (
    "funding",
    "raises",
    "valuation",
    "lawsuit",
    "ban",
    "regulation",
    "layoffs",
    "earnings",
)
SEEN_LIMIT = 500
CANDIDATE_LIMIT = 60

HEADER = "چند خبر تازه از دنیای هوش مصنوعی:"

SYSTEM_INSTRUCTION = (
    "تو از میان تیتر\u200cهای خبری انگلیسی، مهم\u200cترین\u200cها را انتخاب می\u200cکنی و برای هر یک "
    "یک جملهٔ کوتاه فارسی می\u200cنویسی. "
    "معنی هر تیتر را نگه دار و هیچ ادعای تازه\u200cای از خودت به آن اضافه نکن. "
    "فارسی را تازه بنویس، نیم\u200cفاصله را در واژه\u200cهای نیم\u200cفاصله\u200cدار درست بگذار و "
    "پیشوند «نا» را چسبیده بنویس. "
    "مهم\u200cترین خبر را اول بیاور و از هر رویداد فقط یک خبر را نگه دار. "
    "پاسخ را فقط به شکل خط\u200cهای خواسته\u200cشده بنویس؛ بدون مقدمه، بدون عنوان، بدون "
    "مارک\u200cداون و بدون نقل\u200cقول."
)

REWORD_FAILED = "این بار متن تازه نوشته نشد؛ تیتر به انگلیسی می\u200cآید"
FEED_FAILED = "خواندن خوراک خبری ممکن نشد؛ نمی\u200cدانم خبری هست یا نه"

# A story with no date sorts last; the epoch stands in for "no date" and can never
# collide with a real one.
_UNDATED = datetime.min.replace(tzinfo=timezone.utc)
_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


class Chosen(NamedTuple):
    """One model line and the story its index pointed at."""

    line: str
    story: Story


def blocklist_words(raw: str) -> tuple[str, ...]:
    """The comma-separated setting, or the built-in default when it is empty."""
    words = tuple(part.strip() for part in raw.split(",") if part.strip())
    return words or DEFAULT_BLOCKLIST


def blocked(title: str, words: Sequence[str]) -> bool:
    """Whether the title contains one of the words, case-insensitively, as a word."""
    return any(
        re.search(rf"\b{re.escape(word)}\b", title, re.IGNORECASE) for word in words
    )


def newest_first(stories: Sequence[Story]) -> list[Story]:
    """The stories by ``published`` descending, undated last, ties in input order."""
    return sorted(stories, key=lambda story: story.published or _UNDATED, reverse=True)


def seen_guids(state: Mapping[str, object]) -> list[str]:
    """The memory blob's seen guids, oldest first; a bad blob reads as empty."""
    seen = state.get("seen")
    if not isinstance(seen, list):
        return []
    return [guid for guid in seen if isinstance(guid, str)]


def remember(seen: Sequence[str], guids: Iterable[str]) -> list[str]:
    """The guids appended, capped at the newest ``SEEN_LIMIT``."""
    return (list(seen) + list(guids))[-SEEN_LIMIT:]


def build_messages(stories: Sequence[Story], *, max_items: int) -> list[dict[str, str]]:
    """The instruction plus the numbered candidates, ready for ``complete``."""
    lines = [
        f"حداکثر {max_items} خبر را انتخاب کن.",
        "",
        "فهرست تیتر\u200cهای تازه:",
    ]
    for index, story in enumerate(stories, start=1):
        source = f" — {story.source}" if story.source else ""
        lines.append(f"{index}. {story.title}{source}")
    lines += [
        "",
        "پاسخ را دقیقاً به این شکل بنویس و هر خط را با یک خبر پر کن:",
        "<index>|<sentence>",
        "که <index> شمارهٔ خبر در فهرست بالا و <sentence> جملهٔ فارسی تو است.",
    ]
    return [
        {"role": "system", "content": SYSTEM_INSTRUCTION},
        {"role": "user", "content": "\n".join(lines)},
    ]


def parse_answer(
    text: str, stories: Sequence[Story], *, max_items: int
) -> list[Chosen] | None:
    """The model's lines mapped back to stories, or ``None`` on any failure.

    ``None`` means the whole answer is unusable — one bad line fails it, per the
    spec's failure list read literally. A repeated index is not a failure: it is
    collapsed to its first occurrence, since the same story twice is noise. An
    empty sentence is a failure too: ``<index>|`` is the right shape with nothing
    in it, and a numbered item with no Persian line is not a usable answer.
    """
    chosen: list[Chosen] = []
    seen: set[int] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        head, separator, sentence = line.partition("|")
        if not separator:
            return None
        try:
            index = int(head.strip())
        except ValueError:
            return None
        if not 1 <= index <= len(stories):
            return None
        # A sentence of only whitespace or zero-width marks renders a numbered item
        # with nothing visible under it, which is what this rule exists to prevent.
        # `str.strip()` alone would let a lone U+200C through: it is a format
        # character, not whitespace, so stripping does not remove it.
        if not any(char.isprintable() and not char.isspace() for char in sentence):
            return None
        if index in seen:
            continue
        seen.add(index)
        chosen.append(Chosen(line=sentence.strip(), story=stories[index - 1]))
    if not chosen:
        return None
    return chosen[:max_items]


def digest_text(chosen: Sequence[Chosen]) -> str:
    """The header, then each chosen story numbered with Persian digits."""
    blocks = [HEADER]
    for index, item in enumerate(chosen, start=1):
        block = [f"{_persian_number(index)}. {item.line}"]
        # The link is always shown: it is the owner's only way to reach the story,
        # so an item with no source name loses the label, never the address.
        if item.story.source:
            block.append(f"منبع: {item.story.source} — {item.story.link}")
        else:
            block.append(item.story.link)
        blocks.append("\n".join(block))
    return "\n\n".join(blocks)


def raw_text(stories: Sequence[Story], error: str) -> str:
    """The English headlines, then one Persian line naming the reword's failure.

    It adds no cap of its own: the caller slices the survivors, because the cap is
    a setting's business and this only renders what it is given.
    """
    lines: list[str] = []
    for story in stories:
        source = f" — {story.source}" if story.source else ""
        lines.append(f"{story.title}{source}")
        lines.append(story.link)
    if lines:
        lines.append("")
    code = f" ({error})" if error else ""
    lines.append(f"{REWORD_FAILED}{code}.")
    return "\n".join(lines)


def feed_failure_text(error: str) -> str:
    """The Persian line for a feed that could not be read, naming the code.

    It never says there was no news: a read that failed is not a quiet day.
    """
    code = f" ({error})" if error else ""
    return f"{FEED_FAILED}{code}."


def _persian_number(value: int) -> str:
    return str(value).translate(_DIGITS)
