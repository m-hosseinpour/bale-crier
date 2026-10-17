import os
from datetime import datetime, timezone

import pytest

from bale_crier.models import Story
from bale_crier.news.select import (
    CANDIDATE_LIMIT,
    DEFAULT_BLOCKLIST,
    HEADER,
    SEEN_LIMIT,
    Chosen,
    blocked,
    blocklist_words,
    build_messages,
    digest_text,
    feed_failure_text,
    newest_first,
    parse_answer,
    raw_text,
    remember,
    seen_guids,
)

FORBIDDEN_ADVICE = ("بخر", "خرید", "توصیه")
NO_NEWS_CLAIMS = ("خبری نبود", "خبری نیست", "هیچ خبری")


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Run in an empty directory: the developer's own .env must not reach the tests."""
    monkeypatch.chdir(tmp_path)
    for name in list(os.environ):
        if name.startswith("CRIER_"):
            monkeypatch.delenv(name)


def story(
    guid: str,
    *,
    title: str = "A headline",
    source: str = "The Outlet",
    link: str = "https://x.test/1",
    published: datetime | None = None,
) -> Story:
    return Story(
        title=title,
        source=source,
        link=link,
        guid=guid,
        published=published,
    )


def has_persian(text: str) -> bool:
    return any("\u0600" <= char <= "\u06ff" for char in text)


def prompt_blob(stories, *, max_items: int) -> str:
    return "\n".join(message["content"] for message in build_messages(stories, max_items=max_items))


def test_the_limits_are_the_planned_values():
    assert SEEN_LIMIT == 500
    assert CANDIDATE_LIMIT == 60


def test_blocked_is_case_insensitive():
    assert blocked("Startup Funding Round", DEFAULT_BLOCKLIST)
    assert blocked("FUNDING", DEFAULT_BLOCKLIST)


def test_blocked_matches_on_word_boundaries():
    assert not blocked("Urban planning gets an AI helper", DEFAULT_BLOCKLIST)
    assert not blocked("She praises the new model", DEFAULT_BLOCKLIST)


def test_blocked_does_not_fire_on_a_word_it_was_not_given():
    assert not blocked("A lawsuit against the company", ("funding",))


def test_blocklist_words_empty_and_blank_give_the_default():
    assert blocklist_words("") == DEFAULT_BLOCKLIST
    assert blocklist_words(" , ") == DEFAULT_BLOCKLIST


def test_blocklist_words_splits_trims_and_drops_empty_entries():
    assert blocklist_words("ban, funding") == ("ban", "funding")
    assert blocklist_words(" ban ,, funding ") == ("ban", "funding")


def test_newest_first_orders_by_published_descending_with_ties_in_input_order():
    older = story("a", published=datetime(2026, 10, 17, 8, tzinfo=timezone.utc))
    newest = story("b", published=datetime(2026, 10, 17, 9, tzinfo=timezone.utc))
    tie_first = story("c", published=datetime(2026, 10, 17, 9, tzinfo=timezone.utc))
    tie_second = story("d", published=datetime(2026, 10, 17, 9, tzinfo=timezone.utc))

    ordered = newest_first([older, newest, tie_first, tie_second])

    assert [item.guid for item in ordered] == ["b", "c", "d", "a"]


def test_newest_first_puts_a_story_without_a_date_last():
    dated = story("a", published=datetime(2026, 10, 17, 8, tzinfo=timezone.utc))
    undated = story("b")

    assert [item.guid for item in newest_first([undated, dated])] == ["a", "b"]


def test_seen_guids_reads_the_stored_list_oldest_first():
    assert seen_guids({"seen": ["a", "b", "c"]}) == ["a", "b", "c"]


def test_seen_guids_is_empty_for_a_missing_or_bad_blob():
    assert seen_guids({}) == []
    assert seen_guids({"seen": "not a list"}) == []


def test_seen_guids_keeps_only_the_strings():
    assert seen_guids({"seen": ["a", 7, "b", None]}) == ["a", "b"]


def test_remember_appends_the_new_guids():
    assert remember(["a", "b"], ["c", "d"]) == ["a", "b", "c", "d"]


def test_remember_caps_at_the_newest_seen_limit():
    existing = [f"g{i}" for i in range(SEEN_LIMIT)]

    remembered = remember(existing, ["newest"])

    assert len(remembered) == SEEN_LIMIT
    assert remembered[0] == "g1"
    assert remembered[-1] == "newest"
    assert "g0" not in remembered


def test_build_messages_numbers_the_candidates_and_carries_title_and_source():
    content = prompt_blob(
        [
            story("a", title="First headline", source="Outlet One"),
            story("b", title="Second headline", source="Outlet Two"),
        ],
        max_items=3,
    )

    assert "1. First headline — Outlet One" in content
    assert "2. Second headline — Outlet Two" in content


def test_build_messages_states_the_answer_format_and_the_cap():
    blob = prompt_blob([story("a")], max_items=4)

    assert "<index>|<sentence>" in blob
    assert "4" in blob


def test_the_prompt_is_persian_with_a_half_space():
    blob = prompt_blob([story("a")], max_items=5)

    assert has_persian(blob)
    # «می‌کنی»: a half-space word written without U+200C still reads as Persian, so
    # only an explicit check notices the character going missing.
    assert "\u200c" in blob


def test_parse_answer_maps_an_index_to_its_story_and_line():
    stories = [story("a", title="A"), story("b", title="B")]

    chosen = parse_answer("2|متن دوم", stories, max_items=5)

    assert chosen is not None
    assert chosen[0].story.guid == "b"
    assert chosen[0].line == "متن دوم"


def test_parse_answer_keeps_the_answer_order():
    stories = [story("a"), story("b"), story("c")]

    chosen = parse_answer("3|سوم\n1|نخست", stories, max_items=5)

    assert chosen is not None
    assert [item.story.guid for item in chosen] == ["c", "a"]
    assert [item.line for item in chosen] == ["سوم", "نخست"]


def test_a_pipe_inside_the_persian_line_survives():
    chosen = parse_answer("2|متن | با خط عمودی", [story("a"), story("b")], max_items=5)

    assert chosen is not None
    assert chosen[0].line == "متن | با خط عمودی"


def test_an_out_of_range_index_is_a_model_failure():
    assert parse_answer("3|متن", [story("a"), story("b")], max_items=5) is None
    assert parse_answer("0|متن", [story("a"), story("b")], max_items=5) is None


def test_a_line_without_a_pipe_is_a_model_failure():
    assert parse_answer("2 متن", [story("a"), story("b")], max_items=5) is None


def test_an_answer_of_blank_lines_only_is_a_model_failure():
    assert parse_answer("\n  \n\n", [story("a")], max_items=5) is None
    assert parse_answer("", [story("a")], max_items=5) is None


def test_a_line_with_an_empty_sentence_is_a_model_failure():
    """`1|` is the right shape with nothing in it: a numbered item with no Persian
    line is not a usable answer, and the raw fallback is better than a blank item."""
    assert parse_answer("1|", [story("a")], max_items=5) is None
    assert parse_answer("1|   ", [story("a")], max_items=5) is None


def test_one_bad_line_fails_the_whole_answer():
    """The spec's failure list is read literally: a good line is not salvaged."""
    assert parse_answer("1|خوب\nخط دوم", [story("a"), story("b")], max_items=5) is None


def test_a_repeated_index_gives_that_story_once_first_occurrence_winning():
    chosen = parse_answer("1|نخست\n2|دوم\n1|دوباره", [story("a"), story("b")], max_items=5)

    assert chosen is not None
    assert [item.story.guid for item in chosen] == ["a", "b"]
    assert [item.line for item in chosen] == ["نخست", "دوم"]


def test_more_usable_lines_than_max_items_are_truncated_in_answer_order():
    chosen = parse_answer("2|دوم\n3|سوم\n1|نخست", [story("a"), story("b"), story("c")], max_items=2)

    assert chosen is not None
    assert [item.story.guid for item in chosen] == ["b", "c"]


def test_digest_text_renders_the_header_and_numbered_items():
    chosen = [
        Chosen(line="متن نخست", story=story("a", source="The Straits Times", link="https://x.test/1")),
        Chosen(line="متن دوم", story=story("b", source="Outlet Two", link="https://x.test/2")),
    ]

    text = digest_text(chosen)

    assert text.startswith(HEADER)
    assert "۱. متن نخست" in text
    assert "۲. متن دوم" in text
    assert "منبع: The Straits Times — https://x.test/1" in text
    assert "منبع: Outlet Two — https://x.test/2" in text


def test_digest_text_separates_items_with_one_blank_line():
    chosen = [
        Chosen(line="یک", story=story("a", source="S", link="https://x.test/1")),
        Chosen(line="دو", story=story("b", source="S", link="https://x.test/2")),
    ]

    text = digest_text(chosen)

    assert "منبع: S — https://x.test/1\n\n۲. دو" in text
    assert "\n\n\n" not in text


def test_digest_text_keeps_the_link_when_the_source_is_empty():
    text = digest_text([Chosen(line="متن", story=story("a", source="", link="https://x.test/1"))])

    assert "متن" in text
    assert "منبع:" not in text
    # The link is the owner's only way to the story, so it survives an empty source.
    assert "https://x.test/1" in text


def test_raw_text_carries_titles_sources_and_links_and_ends_with_a_persian_line():
    stories = [
        story("a", title="First headline", source="Outlet One", link="https://x.test/1"),
        story("b", title="Second headline", source="Outlet Two", link="https://x.test/2"),
    ]

    text = raw_text(stories, "HTTP 500")

    assert "First headline" in text
    assert "Outlet One" in text
    assert "https://x.test/1" in text
    assert "Second headline" in text
    assert "https://x.test/2" in text
    last = text.rstrip().splitlines()[-1]
    assert "HTTP 500" in last
    assert has_persian(last)
    assert has_persian(text)
    assert "\u200c" in text


def test_feed_failure_text_names_the_code_and_never_claims_there_was_no_news():
    text = feed_failure_text("HTTP 500")

    assert "HTTP 500" in text
    assert "ممکن نشد" in text
    assert has_persian(text)
    assert "\u200c" in text
    for claim in NO_NEWS_CLAIMS:
        assert claim not in text


def test_no_message_text_advises_a_purchase():
    blobs = [
        digest_text([Chosen(line="متن", story=story("a", source="S", link="https://x.test/1"))]),
        raw_text([story("a", title="Headline", source="S", link="https://x.test/1")], "HTTP 500"),
        feed_failure_text("HTTP 500"),
        prompt_blob([story("a")], max_items=5),
    ]

    for blob in blobs:
        for word in FORBIDDEN_ADVICE:
            assert word not in blob
