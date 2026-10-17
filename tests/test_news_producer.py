import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from bale_crier.config import Settings
from bale_crier.llm import LlmRead
from bale_crier.memory import WatcherMemory
from bale_crier.models import Story
from bale_crier.news.feed import FeedRead
from bale_crier.news.producer import NewsProducer
from bale_crier.news.select import CANDIDATE_LIMIT, Chosen, digest_text, feed_failure_text

NOW = datetime(2026, 10, 17, 8, 30, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Run in an empty directory: the developer's own .env must not reach the tests."""
    monkeypatch.chdir(tmp_path)
    for name in list(os.environ):
        if name.startswith("CRIER_"):
            monkeypatch.delenv(name)


def settings(**overrides) -> Settings:
    fields = {
        "bale_bot_token": "token",
        "bale_chat_id": 7,
        "open_ai_api_key": "key",
    }
    fields.update(overrides)
    return Settings(**fields)


def memory(tmp_path) -> WatcherMemory:
    return WatcherMemory.load(tmp_path / "data" / "watchers.json")


def story(
    guid: str,
    *,
    title: str = "A headline",
    source: str = "The Outlet",
    link: str = "https://x.test/1",
    published: datetime | None = None,
) -> Story:
    return Story(title=title, source=source, link=link, guid=guid, published=published)


def stub_read(stories, *, error: str = ""):
    calls = []

    def read(*, url, timeout=30):
        calls.append({"url": url, "timeout": timeout})
        return FeedRead(stories, error)

    return read, calls


def stub_llm(text: str = "1|متن یک"):
    calls = []

    def complete(messages, **kwargs):
        calls.append({"messages": messages, **kwargs})
        return LlmRead(text=text, error="")

    return complete, calls


def failing_llm(error: str = "HTTP 500"):
    def complete(messages, **kwargs):
        return LlmRead(text=None, error=error)

    return complete


def has_persian(text: str) -> bool:
    return any("\u0600" <= char <= "\u06ff" for char in text)


def test_the_producer_owns_its_timer(tmp_path):
    producer = NewsProducer(settings(), memory(tmp_path), read=stub_read([])[0])

    assert producer.name == "news"
    assert producer.own_timer is True


def test_a_failed_feed_read_gives_the_persian_failure_line(tmp_path):
    read, _ = stub_read(None, error="HTTP 503")
    complete, calls = stub_llm()

    bulletins = NewsProducer(settings(), memory(tmp_path), read=read, complete=complete).produce(NOW)

    assert len(bulletins) == 1
    assert bulletins[0].kind == "news"
    assert bulletins[0].text == feed_failure_text("HTTP 503")
    assert "HTTP 503" in bulletins[0].text
    assert has_persian(bulletins[0].text)
    assert calls == []


def test_a_feed_where_every_story_is_blocked_gives_nothing(tmp_path):
    read, _ = stub_read(
        [
            story("g1", title="A startup raises funding"),
            story("g2", title="The valuation everyone argues about"),
        ]
    )
    complete, calls = stub_llm()
    mem = memory(tmp_path)

    bulletins = NewsProducer(settings(), mem, read=read, complete=complete).produce(NOW)

    assert bulletins == []
    assert calls == []
    assert mem.get("news") == {}


def test_a_feed_where_every_story_is_already_seen_gives_nothing(tmp_path):
    read, _ = stub_read([story("g1"), story("g2")])
    complete, calls = stub_llm()
    mem = memory(tmp_path)
    mem.set("news", {"seen": ["g1", "g2"]})

    bulletins = NewsProducer(settings(), mem, read=read, complete=complete).produce(NOW)

    assert bulletins == []
    assert calls == []


def test_a_feed_failure_writes_nothing_to_the_memory_file(tmp_path):
    read, _ = stub_read(None, error="HTTP 503")
    mem = memory(tmp_path)

    NewsProducer(settings(), mem, read=read, complete=stub_llm()[0]).produce(NOW)
    mem.save()

    assert not (tmp_path / "data" / "watchers.json").exists()


def test_a_run_with_no_survivors_writes_nothing_to_the_memory_file(tmp_path):
    read, _ = stub_read([story("g1", title="A startup raises funding")])
    mem = memory(tmp_path)

    NewsProducer(settings(), mem, read=read, complete=stub_llm()[0]).produce(NOW)
    mem.save()

    assert not (tmp_path / "data" / "watchers.json").exists()


def test_the_candidates_are_newest_first_and_capped(tmp_path):
    base = datetime(2026, 10, 17, 6, 0, tzinfo=timezone.utc)
    stories = [
        story(f"g{i}", title=f"Headline {i}", published=base + timedelta(minutes=i))
        for i in range(CANDIDATE_LIMIT + 5)
    ]
    read, _ = stub_read(stories)
    complete, calls = stub_llm()

    NewsProducer(settings(), memory(tmp_path), read=read, complete=complete).produce(NOW)

    prompt = calls[0]["messages"][-1]["content"]
    numbered = [line for line in prompt.splitlines() if line[:1].isdigit()]
    assert len(numbered) == CANDIDATE_LIMIT
    # The newest survivor is first, and the oldest fell off the cap.
    assert f"Headline {CANDIDATE_LIMIT + 4}" in numbered[0]
    assert "Headline 0" not in prompt


def test_the_feed_and_the_model_are_called_with_the_configured_values(tmp_path):
    read, read_calls = stub_read([story("g1")])
    complete, llm_calls = stub_llm()
    producer = NewsProducer(
        settings(
            news_feed_url="https://feed.test/rss",
            http_timeout=7,
            open_ai_model="a-model",
            open_ai_base_url="https://llm.test/v1",
        ),
        memory(tmp_path),
        read=read,
        complete=complete,
    )

    producer.produce(NOW)

    assert read_calls == [{"url": "https://feed.test/rss", "timeout": 7}]
    assert llm_calls[0]["key"] == "key"
    assert llm_calls[0]["model"] == "a-model"
    assert llm_calls[0]["base_url"] == "https://llm.test/v1"
    # A configured timeout must not be silently ignored in favour of the default.
    assert llm_calls[0]["timeout"] == 7


def test_a_parsed_answer_becomes_the_digest(tmp_path):
    first = story("g1", title="First headline", link="https://x.test/1")
    read, _ = stub_read([first])
    complete, _ = stub_llm(text="1|متن یک")

    bulletins = NewsProducer(settings(), memory(tmp_path), read=read, complete=complete).produce(NOW)

    assert len(bulletins) == 1
    assert bulletins[0].kind == "news"
    assert bulletins[0].text == digest_text([Chosen(line="متن یک", story=first)])
    assert bulletins[0].note_id is None
    assert bulletins[0].list_name is None


def test_a_failed_model_call_gives_the_raw_headlines(tmp_path):
    older = story(
        "g-old", title="Older headline", published=datetime(2026, 10, 17, 6, 0, tzinfo=timezone.utc)
    )
    newer = story(
        "g-new", title="Newer headline", published=datetime(2026, 10, 17, 7, 0, tzinfo=timezone.utc)
    )
    read, _ = stub_read([older, newer])
    mem = memory(tmp_path)

    bulletins = NewsProducer(
        settings(news_max_items=1), mem, read=read, complete=failing_llm("HTTP 500")
    ).produce(NOW)

    assert len(bulletins) == 1
    text = bulletins[0].text
    assert "Newer headline" in text
    assert "Older headline" not in text
    assert "HTTP 500" in text
    assert has_persian(text)
    assert "\u200c" in text


def test_an_unparsable_answer_gives_the_raw_headlines_with_its_code(tmp_path):
    read, _ = stub_read([story("g1", title="A headline")])
    complete, _ = stub_llm(text="no pipe on this line")
    mem = memory(tmp_path)

    bulletins = NewsProducer(settings(), mem, read=read, complete=complete).produce(NOW)

    assert len(bulletins) == 1
    assert "A headline" in bulletins[0].text
    assert "unparsable answer" in bulletins[0].text
    assert mem.get("news") == {"seen": ["g1"]}


def test_a_digest_marks_its_stories_seen_so_the_next_run_is_quiet(tmp_path):
    read, _ = stub_read([story("g1")])
    complete, _ = stub_llm(text="1|متن یک")
    mem = memory(tmp_path)
    producer = NewsProducer(settings(), mem, read=read, complete=complete)

    assert len(producer.produce(NOW)) == 1
    assert mem.get("news") == {"seen": ["g1"]}

    assert producer.produce(NOW) == []


def test_a_story_already_in_the_seen_set_never_reaches_the_model(tmp_path):
    read, _ = stub_read(
        [story("g-seen", title="Seen headline"), story("g-fresh", title="Fresh headline")]
    )
    complete, calls = stub_llm()
    mem = memory(tmp_path)
    mem.set("news", {"seen": ["g-seen"]})

    NewsProducer(settings(), mem, read=read, complete=complete).produce(NOW)

    prompt = calls[0]["messages"][-1]["content"]
    assert "Fresh headline" in prompt
    assert "Seen headline" not in prompt


def test_the_stories_the_failure_bulletin_carried_are_marked_seen(tmp_path):
    stories = [story(f"g{i}", title=f"Headline {i}") for i in range(7)]
    read, _ = stub_read(stories)
    mem = memory(tmp_path)

    bulletins = NewsProducer(
        settings(news_max_items=5), mem, read=read, complete=failing_llm("HTTP 500")
    ).produce(NOW)

    assert len(bulletins) == 1
    assert mem.get("news") == {"seen": ["g0", "g1", "g2", "g3", "g4"]}


def test_the_memory_blob_is_the_one_the_store_writes(tmp_path):
    read, _ = stub_read([story("g1")])
    mem = memory(tmp_path)

    NewsProducer(settings(), mem, read=read, complete=stub_llm(text="1|متن یک")[0]).produce(NOW)
    mem.save()

    blob = json.loads((tmp_path / "data" / "watchers.json").read_text(encoding="utf-8"))
    assert blob["news"] == {"seen": ["g1"]}
