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
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import NamedTuple, TypeVar

from ..models import Story
from ..persian import digits

DEFAULT_BLOCKLIST: tuple[str, ...] = (
    "funding",
    "raises",
    "valuation",
    "lawsuit",
    "ban",
    "regulation",
    "layoffs",
    "earnings",
    # Consumer-device words: the feed's phrasing ("new features", "now available",
    # "update") also matches phone, gaming and driver releases, and these are the
    # words the real titles carried. Measured on three days of feeds: they drop the
    # device news and no story about a model or a tool.
    "iPhone",
    "iOS",
    "Android",
    "gaming",
    "laptop",
    "laptops",
    "GPU",
    "driver",
    "drivers",
    "DLSS",
    "Fitbit",
    "Sims",
    "Chrome",
    "Netflix",
)
SEEN_LIMIT = 500
CANDIDATE_LIMIT = 60

# Bale's sendMessage accepts 1 to 4096 characters, and ten stories with their
# Google News links went past it: the API refused the whole message and the owner was
# told nothing. A small margin is kept under the documented limit because the count
# is the server's, not this one's.
TEXT_CHARS = 4000

HEADER = "چند خبر تازه از دنیای هوش مصنوعی:"

# Bale formats every message as Markdown, so a link can carry a label instead of
# filling the message with a Google News address. The source name is the owner's
# choice of label; this is what a story with no source shows instead.
LINK_FALLBACK = "لینک خبر"

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


class Chosen(NamedTuple):
    """One model line and the story its index pointed at."""

    line: str
    story: Story


def markdown_link(label: str, url: str) -> str:
    """The address as a Markdown link under ``label``, safe to paste into a message.

    A ``]`` in the label would close it early and spill the rest of the line as text,
    so brackets are dropped from the label — a source name is a name with or without
    them. Parentheses in the address would end it the same way, and percent-encoding
    those two characters leaves the same address, one a browser still opens.
    """
    clean = label.replace("[", "").replace("]", "").strip() or LINK_FALLBACK
    return f"[{clean}]({url.replace('(', '%28').replace(')', '%29')})"


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
        block = [f"{digits(index)}. {item.line}"]
        # The link is always shown, and it is the owner's only way to reach the story;
        # it rides on the source name rather than filling the line with the address.
        if item.story.source:
            block.append(f"منبع: {markdown_link(item.story.source, item.story.link)}")
        else:
            block.append(markdown_link(LINK_FALLBACK, item.story.link))
        blocks.append("\n".join(block))
    return "\n\n".join(blocks)


def raw_text(stories: Sequence[Story], error: str) -> str:
    """The English headlines, then one Persian line naming the reword's failure.

    It adds no cap of its own: the caller slices the survivors, because the cap is
    a setting's business and this only renders what it is given.
    """
    lines: list[str] = []
    for story in stories:
        # One line per story, and the headline itself carries the address: the
        # fallback exists to show the English text, not to spell out a URL.
        label = f"{story.title} — {story.source}" if story.source else story.title
        lines.append(markdown_link(label, story.link))
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


T = TypeVar("T")


def grouped(
    items: Sequence[T], *, batch_size: int, render: Callable[[Sequence[T]], str]
) -> list[str]:
    """The rendered messages: at most ``batch_size`` items each, each under Bale's limit.

    Two rules, two owners. ``batch_size`` is the owner's — he reads the digest in
    groups of that many stories. ``TEXT_CHARS`` is the API's, and it refuses the
    whole message rather than cutting it, so a group closes early when the next
    item would cross it; the group's numbering restarts, because each message is
    read on its own.

    An item that alone crosses the limit still ships alone, uncut: the link is the
    owner's only way to the story, and a cut link is a dead one. Against the real
    feed this branch cannot fire — its links run 150 to 650 characters, and one item
    would need four thousand — so it is a guard, not a path the digest takes. If it
    ever did fire, that message would be refused and the history would record it,
    rather than the story disappearing quietly.
    """
    messages: list[str] = []
    current: list[T] = []
    for item in items:
        candidate = current + [item]
        full = len(candidate) > batch_size
        if current and (full or len(render(candidate)) > TEXT_CHARS):
            messages.append(render(current))
            current = [item]
        else:
            current = candidate
    if current:
        messages.append(render(current))
    return messages

