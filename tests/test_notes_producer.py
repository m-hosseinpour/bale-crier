import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bale_crier.config import Settings
from bale_crier.history import append
from bale_crier.llm import LlmRead
from bale_crier.models import HistoryRecord
from bale_crier.notes.producer import NoteProducer
from bale_crier.notes.reword import PREVIOUS_LIMIT

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
        "lists_dir": Path("lists"),
        "history_path": Path("data/history.jsonl"),
        "open_ai_api_key": "key",
    }
    fields.update(overrides)
    return Settings(**fields)


def write_list(body: str, *, name: str = "reading") -> None:
    path = Path("lists") / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def stub_llm(text: str = "متن تازهٔ امروز"):
    calls = []

    def complete(messages, **kwargs):
        calls.append({"messages": messages, **kwargs})
        return LlmRead(text=text, error="")

    return complete, calls


def record(note_id: str, *, text: str = "متن پیشین", ok: bool = True, ts: datetime = NOW) -> None:
    append(
        HistoryRecord(
            ts=ts,
            kind="note",
            text=text,
            list_name="reading",
            note_id=note_id,
            ok=ok,
        ),
        path=Path("data/history.jsonl"),
        max_lines=5000,
    )


def test_a_missing_lists_directory_produces_nothing():
    complete, calls = stub_llm()

    bulletins = NoteProducer(settings(), complete=complete).produce(NOW)

    assert bulletins == []
    assert calls == []


def test_one_note_becomes_one_bulletin_carrying_its_identity():
    write_list("## reading-1\nهر روز یک صفحه کتاب بخوان\n")
    complete, _ = stub_llm()

    bulletins = NoteProducer(settings(), complete=complete).produce(NOW)

    assert len(bulletins) == 1
    assert bulletins[0].kind == "note"
    assert bulletins[0].note_id == "reading-1"
    assert bulletins[0].list_name == "reading"
    assert bulletins[0].text == "متن تازهٔ امروز"


def test_the_model_is_given_the_note_and_the_wordings_already_sent():
    write_list("## reading-1\nهر روز یک صفحه کتاب بخوان\n")
    record("reading-1", text="هر روز چند صفحه بخوان")
    complete, calls = stub_llm()

    NoteProducer(settings(), complete=complete).produce(NOW)

    prompt = "\n".join(message["content"] for message in calls[0]["messages"])
    assert "هر روز یک صفحه کتاب بخوان" in prompt
    assert "هر روز چند صفحه بخوان" in prompt


def test_only_the_newest_wordings_are_offered_to_the_model():
    write_list("## reading-1\nهر روز یک صفحه کتاب بخوان\n")
    for i in range(1, PREVIOUS_LIMIT + 2):
        record("reading-1", text=f"متن پیشین {i}", ts=NOW + timedelta(minutes=i))
    complete, calls = stub_llm()

    NoteProducer(settings(), complete=complete).produce(NOW)

    prompt = "\n".join(message["content"] for message in calls[0]["messages"])
    assert "متن پیشین 1" not in prompt
    for i in range(2, PREVIOUS_LIMIT + 2):
        assert f"متن پیشین {i}" in prompt


def test_a_failed_reword_still_produces_the_note_itself():
    write_list("## reading-1\nهر روز یک صفحه کتاب بخوان\n")

    def complete(messages, **kwargs):
        return LlmRead(text=None, error="HTTP 500")

    bulletins = NoteProducer(settings(), complete=complete).produce(NOW)

    assert len(bulletins) == 1
    assert bulletins[0].text.startswith("هر روز یک صفحه کتاب بخوان")
    assert bulletins[0].note_id == "reading-1"
    assert bulletins[0].list_name == "reading"


def test_the_cycle_moves_on_once_a_note_has_gone():
    write_list("## reading-1\nاول\n\n## reading-2\nدوم\n")
    record("reading-1")
    complete, _ = stub_llm()

    bulletins = NoteProducer(settings(), complete=complete).produce(NOW)

    assert [bulletin.note_id for bulletin in bulletins] == ["reading-2"]


def test_a_failed_send_does_not_move_the_cycle_on():
    """The history only counts what actually went, so a failed note comes back."""
    write_list("## reading-1\nاول\n\n## reading-2\nدوم\n")
    record("reading-1", ok=False)
    complete, _ = stub_llm()

    bulletins = NoteProducer(settings(), complete=complete).produce(NOW)

    assert [bulletin.note_id for bulletin in bulletins] == ["reading-1"]


def test_the_producer_is_part_of_the_note_run():
    producer = NoteProducer(settings(), complete=stub_llm()[0])

    assert producer.name == "note"
    assert producer.own_timer is False
