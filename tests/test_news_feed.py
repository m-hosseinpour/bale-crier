import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import requests

from bale_crier.news.feed import (
    DEFAULT_FEED_URL,
    DEFAULT_QUERY,
    fetch_feed,
    parse_feed,
)

# Every test module in this project chdirs into tmp_path, so the fixture is found
# relative to this file, never to the working directory.
FIXTURE = Path(__file__).parent / "fixtures" / "news_feed.xml"


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Run in an empty directory: the developer's own .env must not reach the tests."""
    monkeypatch.chdir(tmp_path)
    for name in list(os.environ):
        if name.startswith("CRIER_"):
            monkeypatch.delenv(name)


def fixture_bytes() -> bytes:
    return FIXTURE.read_bytes()


def feed(*items: str) -> bytes:
    body = "".join(items)
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<rss version="2.0"><channel><title>t</title>{body}</channel></rss>'
    )
    return document.encode("utf-8")


def item(
    *,
    title: str | None = None,
    link: str | None = None,
    guid: str | None = None,
    pub: str | None = None,
    source: str | None = None,
    source_url: str | None = None,
) -> str:
    parts: list[str] = []
    if title is not None:
        parts.append(f"<title>{title}</title>")
    if link is not None:
        parts.append(f"<link>{link}</link>")
    if guid is not None:
        parts.append(f"<guid>{guid}</guid>")
    if pub is not None:
        parts.append(f"<pubDate>{pub}</pubDate>")
    if source is not None:
        url = f' url="{source_url}"' if source_url else ""
        parts.append(f"<source{url}>{source}</source>")
    return f"<item>{''.join(parts)}</item>"


class FakeResponse:
    def __init__(self, body: bytes, status_code: int = 200) -> None:
        self.content = body
        self.status_code = status_code


def stub_get(monkeypatch, response: FakeResponse) -> dict:
    captured: dict = {}

    def fake_get(url, timeout=None):
        captured["url"] = url
        captured["timeout"] = timeout
        return response

    monkeypatch.setattr(requests, "get", fake_get)
    return captured


def test_parse_feed_on_the_real_fixture_gives_54_complete_stories():
    stories = parse_feed(fixture_bytes())

    assert len(stories) == 54
    for story in stories:
        assert story.title.strip()
        assert story.link.strip()
        assert story.guid.strip()


def test_the_first_item_loses_its_source_suffix_and_names_the_outlet():
    story = parse_feed(fixture_bytes())[0]

    assert story.source == "California Employment Law Report"
    assert story.title == (
        "California Bans AI That Reads Employees' Moods (AB 1883) — "
        "Five Takeaways from Our 2027 New Laws Masterclass"
    )


def test_a_url_shaped_source_is_shown_by_its_hostname_and_the_title_is_stripped():
    stories = parse_feed(fixture_bytes())

    # The two items whose <source> text is a URL, at the fixture's own positions.
    codex, airnav = stories[1], stories[49]

    assert codex.source == "tech-insider.org"
    assert codex.title == "Codex CLI 0.163 Update: Mid-Response Steering by Default"
    assert airnav.source == "streamlinefeed.co.ke"
    assert airnav.title == "AirNav Indonesia’s NOTAM AI Deployment Status Remains Unclear"


def test_published_is_a_timezone_aware_utc_datetime():
    story = parse_feed(fixture_bytes())[0]

    assert story.published is not None
    assert story.published.tzinfo is not None
    assert story.published.utcoffset() == timedelta(0)
    assert story.published == datetime(2026, 10, 17, 9, 43, 16, tzinfo=timezone.utc)


def test_an_unparsable_pubdate_gives_none_and_is_still_a_story():
    document = feed(item(title="A headline", link="https://x.test/1", pub="not a date"))

    stories = parse_feed(document)

    assert len(stories) == 1
    assert stories[0].published is None


def test_an_item_without_a_guid_uses_its_link():
    document = feed(item(title="A headline", link="https://x.test/1"))

    story = parse_feed(document)[0]

    assert story.guid == "https://x.test/1"


def test_items_without_a_title_or_a_link_are_skipped_and_the_rest_parses():
    document = feed(
        item(link="https://x.test/1"),
        item(title="No link"),
        item(title="Good", link="https://x.test/2"),
    )

    stories = parse_feed(document)

    assert [story.title for story in stories] == ["Good"]


def test_a_title_without_the_source_suffix_is_left_whole():
    document = feed(item(title="Just a headline", link="https://x.test/1", source="The Outlet"))

    story = parse_feed(document)[0]

    assert story.title == "Just a headline"
    assert story.source == "The Outlet"


def test_an_item_without_a_source_keeps_its_title_and_has_an_empty_source():
    document = feed(item(title="Odd headline - ", link="https://x.test/1"))

    story = parse_feed(document)[0]

    assert story.source == ""
    assert story.title == "Odd headline - "


def test_a_readable_feed_with_no_items_is_empty():
    assert parse_feed(feed()) == []


def test_a_document_that_is_not_xml_raises_value_error():
    with pytest.raises(ValueError):
        parse_feed(b"this is not xml at all")


def test_an_xml_document_that_is_not_rss_raises_value_error():
    """A 200 that is not the feed must not read as a quiet day."""
    with pytest.raises(ValueError):
        parse_feed(b"<html><body>a search page</body></html>")


def test_an_rss_without_a_channel_raises_value_error():
    with pytest.raises(ValueError):
        parse_feed(b'<rss version="2.0"></rss>')


def test_fetch_feed_returns_the_parsed_stories_and_passes_url_and_timeout(monkeypatch):
    captured = stub_get(monkeypatch, FakeResponse(fixture_bytes()))

    read = fetch_feed(url="https://example.test/feed", timeout=7)

    assert read.error == ""
    assert read.stories is not None
    assert len(read.stories) == 54
    assert captured == {"url": "https://example.test/feed", "timeout": 7}


def test_a_non_200_gives_an_error_carrying_the_status(monkeypatch):
    stub_get(monkeypatch, FakeResponse(b"", status_code=403))

    read = fetch_feed(url="https://example.test/feed")

    assert read.stories is None
    assert "403" in read.error


def test_a_200_that_is_not_a_feed_gives_an_error(monkeypatch):
    stub_get(monkeypatch, FakeResponse(b"<html><body>not the feed</body></html>"))

    read = fetch_feed(url="https://example.test/feed")

    assert read.stories is None
    assert read.error


def test_a_transport_error_gives_an_error_and_raises_nothing(monkeypatch):
    def failing_get(url, timeout=None):
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr(requests, "get", failing_get)

    read = fetch_feed(url="https://example.test/feed")

    assert read.stories is None
    assert read.error


def test_the_default_query_is_the_owner_query_verbatim():
    assert DEFAULT_QUERY == (
        '"new features" OR "now available" OR "update" OR "version" AI '
        "(tool OR model) -investment -funding -startup -stocks when:1d"
    )


def test_default_feed_url_is_the_query_url_encoded():
    assert DEFAULT_FEED_URL.startswith("https://news.google.com/rss/search?q=")

    query = parse_qs(urlparse(DEFAULT_FEED_URL).query)["q"][0]

    assert query == DEFAULT_QUERY
