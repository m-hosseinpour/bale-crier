"""The Google News RSS feed, fetched and parsed into stories.

The parse is a pure function and raises on a document it cannot read; the fetch is
the boundary and turns every failure into a value. The split exists because a
caller that cannot tell "unreadable" from "empty" would announce a broken feed as a
quiet news day — the one reading the owner must never get.

Nothing here reads a setting or resolves the item's Google redirect link: the story
carries the link as it came, and the owner's browser resolves it when he taps it.
"""

import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import NamedTuple
from urllib.parse import quote, urlparse

import requests

from ..history import as_utc
from ..models import Story

# The owner's query, written here once and nowhere else.
DEFAULT_QUERY = (
    '"new features" OR "now available" OR "update" OR "version" AI '
    "(tool OR model) -investment -funding -startup -stocks when:1d"
)
DEFAULT_FEED_URL = "https://news.google.com/rss/search?q=" + quote(DEFAULT_QUERY)


class FeedRead(NamedTuple):
    """The outcome of one feed read. A failure is a value, never an exception."""

    stories: list[Story] | None
    error: str


FeedReader = Callable[..., FeedRead]


def fetch_feed(*, url: str, timeout: int = 30) -> FeedRead:
    """The feed's stories, or ``None`` and a short error code. Never raises."""
    try:
        response = requests.get(url, timeout=timeout)
    except requests.RequestException:
        return FeedRead(None, "transport error")

    if response.status_code != 200:
        return FeedRead(None, f"HTTP {response.status_code}")

    try:
        return FeedRead(parse_feed(response.content), "")
    except ValueError:
        # A 200 that is not the feed — an HTML error page, say — must not read as
        # a quiet day.
        return FeedRead(None, "unparsable feed")


def parse_feed(document: bytes | str) -> list[Story]:
    """The document's stories, in feed order. Raises ``ValueError`` on a bad feed.

    A readable feed with no items is ``[]``, a real answer; only a document that
    is not a feed at all raises.
    """
    if isinstance(document, str):
        # ElementTree refuses a str carrying an encoding declaration, and the feed
        # always has one; bytes let the declaration decide the encoding.
        document = document.encode("utf-8")
    try:
        root = ET.fromstring(document)
    except ET.ParseError as exc:
        # ParseError is a SyntaxError, not a ValueError, so it is re-raised as one.
        raise ValueError("not a readable feed") from exc
    if root.tag != "rss":
        raise ValueError("root is not <rss>")
    channel = root.find("channel")
    if channel is None:
        raise ValueError("no <channel>")

    stories: list[Story] = []
    for item in channel.findall("item"):
        story = _story(item)
        if story is not None:
            stories.append(story)
    return stories


def _story(item: ET.Element) -> Story | None:
    title = item.findtext("title")
    link = item.findtext("link")
    # A story without a headline or a link is not one: it is dropped, and the rest
    # of the feed still parses.
    if not title or not link:
        return None

    element = item.find("source")
    raw_source = (element.text or "").strip() if element is not None else ""
    return Story(
        title=_strip_suffix(title, raw_source),
        source=_display_source(raw_source),
        link=link,
        guid=item.findtext("guid") or link,
        published=_published(item.findtext("pubDate")),
    )


def _strip_suffix(title: str, raw_source: str) -> str:
    # Google appends " - " plus the item's own <source> text, so that text is what
    # is stripped, while the displayed source may be its hostname instead.
    suffix = f" - {raw_source}"
    if raw_source and title.endswith(suffix):
        return title[: -len(suffix)]
    return title


def _display_source(raw_source: str) -> str:
    try:
        parsed = urlparse(raw_source)
    except ValueError:
        # A malformed source URL is not worth failing the whole feed over.
        return raw_source
    if parsed.scheme in ("http", "https") and parsed.hostname:
        return parsed.hostname
    return raw_source


def _published(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    return as_utc(parsed)
