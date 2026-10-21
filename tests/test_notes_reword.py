import os
from collections.abc import Sequence

import pytest

from bale_crier.config import Settings
from bale_crier.llm import LlmRead
from bale_crier.models import Note
from bale_crier.notes.reword import (
    PREVIOUS_LIMIT,
    SYSTEM_INSTRUCTION,
    build_messages,
    fallback_text,
    reword,
)

FORBIDDEN = ["بخر", "خرید", "توصیه"]


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
        "open_ai_api_key": "secret",
        "open_ai_model": "deepseek-v4-flash",
        "open_ai_base_url": "https://api.avalai.ir/v1",
    }
    fields.update(overrides)
    return Settings(**fields)


def note(text: str = "هر روز ده دقیقه کتاب بخوان") -> Note:
    return Note(list_name="reading", id="reading-1", text=text)


def prompt_text(target: Note, previous: Sequence[str] = ()) -> str:
    return "\n".join(message["content"] for message in build_messages(target, previous))


def stub(result: LlmRead):
    calls = []

    def fake(messages, **kwargs):
        calls.append({"messages": messages, **kwargs})
        return result

    return fake, calls


def has_persian(text: str) -> bool:
    return any("\u0600" <= char <= "\u06ff" for char in text)


def test_previous_limit_is_three():
    assert PREVIOUS_LIMIT == 3


def test_the_built_messages_carry_the_note_own_text():
    text = "هر روز ده دقیقه کتاب بخوان"

    assert text in prompt_text(note(text))


def test_each_previous_wording_appears_in_the_built_messages():
    messages = prompt_text(note(), ["متن نخست", "متن دوم"])

    assert "متن نخست" in messages
    assert "متن دوم" in messages


def test_with_no_previous_wordings_the_messages_are_still_built():
    messages = build_messages(note(), [])

    assert messages
    assert note().text in "\n".join(message["content"] for message in messages)


def test_the_messages_are_persian_and_the_instruction_keeps_its_half_spaces():
    messages = build_messages(note(), [])

    joined = "\n".join(message["content"] for message in messages)
    assert has_persian(joined)
    # «می‌کنی»: a half-space word written without U+200C still reads as Persian,
    # so only an explicit check notices the character going missing.
    assert "\u200c" in messages[0]["content"]
    # The model drops the character unless the instruction carries a worked
    # example: one real bulletin went out with «میآید» before this was added.
    assert "می‌شود" in SYSTEM_INSTRUCTION
    assert "تجربه‌ها" in SYSTEM_INSTRUCTION


def test_the_instruction_asks_for_a_paragraph_of_three_or_four_sentences():
    assert "پاراگراف" in SYSTEM_INSTRUCTION
    assert "سه تا چهار" in SYSTEM_INSTRUCTION


def test_the_instruction_no_longer_settles_for_one_short_sentence():
    # The owner's ruling (2026-10-21): a footnote-length note is not worth sending;
    # "کوتاه" is what used to pull the answer back down to one line.
    assert "کوتاه" not in SYSTEM_INSTRUCTION
    assert "یک جمله" not in SYSTEM_INSTRUCTION


def test_the_instruction_forbids_inventing_facts():
    assert "هیچ عدد" in SYSTEM_INSTRUCTION
    assert "نساز" in SYSTEM_INSTRUCTION


def test_a_successful_reword_returns_the_model_text_exactly():
    complete, _ = stub(LlmRead(text="متن تازه", error=""))

    assert reword(note(), [], settings=settings(), complete=complete) == "متن تازه"


def test_a_failed_reword_still_starts_with_the_note_own_text():
    complete, _ = stub(LlmRead(text=None, error="HTTP 500"))

    result = reword(note(), [], settings=settings(), complete=complete)

    assert result.startswith(note().text)


def test_the_fallback_names_the_failure_and_carries_the_error_code():
    text = fallback_text(note(), "HTTP 500")

    assert note().text in text
    assert "انجام نشد" in text
    assert "(HTTP 500)" in text
    assert "()" not in fallback_text(note(), "")


def test_the_fallback_is_persian_with_a_half_space():
    text = fallback_text(note(), "transport error")

    assert has_persian(text)
    assert "\u200c" in text


def test_neither_the_prompt_nor_the_fallback_advises_a_purchase():
    blob = prompt_text(note(), ["متن پیشین"]) + "\n" + fallback_text(note(), "HTTP 500")

    assert not [word for word in FORBIDDEN if word in blob]


def test_reword_passes_the_settings_through_to_the_call():
    complete, calls = stub(LlmRead(text="متن", error=""))
    config = settings(
        open_ai_api_key="k",
        open_ai_model="m",
        open_ai_base_url="https://example.test/v1",
        open_ai_timeout=99,
    )

    reword(note(), [], settings=config, complete=complete)

    assert calls[0]["key"] == "k"
    assert calls[0]["model"] == "m"
    assert calls[0]["base_url"] == "https://example.test/v1"
    # The model's own allowance, not the project's HTTP one: a slow reasoning model
    # would otherwise be cut off and the note would silently fall back.
    assert calls[0]["timeout"] == 99


def test_an_empty_text_that_claims_success_still_returns_a_usable_string():
    complete, _ = stub(LlmRead(text="", error=""))

    result = reword(note(), [], settings=settings(), complete=complete)

    assert result.strip()
    assert note().text in result
