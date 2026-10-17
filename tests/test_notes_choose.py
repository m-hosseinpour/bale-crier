from datetime import datetime, timedelta, timezone

from bale_crier.models import Note
from bale_crier.notes.choose import choose_note

NOW = datetime(2026, 10, 17, 8, 30, tzinfo=timezone.utc)


def note(id: str, *, list_name: str = "reading") -> Note:
    return Note(list_name=list_name, id=id, text="یادداشت‌ها")


def test_a_note_that_never_went_is_chosen_over_one_that_has():
    used = note("used")
    fresh = note("fresh")
    last_sent = {("reading", "used"): NOW - timedelta(days=90)}

    chosen = choose_note([used, fresh], last_sent=last_sent)

    assert chosen is fresh


def test_among_sent_notes_the_oldest_send_goes_first():
    recent = note("recent")
    stale = note("stale")
    last_sent = {
        ("reading", "recent"): NOW - timedelta(days=60),
        ("reading", "stale"): NOW - timedelta(days=90),
    }

    chosen = choose_note([recent, stale], last_sent=last_sent)

    assert chosen is stale


def test_two_never_sent_notes_give_the_first_in_input_order():
    first = note("first")
    second = note("second")

    chosen = choose_note([first, second], last_sent={})

    assert chosen is first


def test_two_notes_with_the_same_last_send_give_the_first_in_input_order():
    first = note("first")
    second = note("second")
    same = NOW - timedelta(days=10)

    chosen = choose_note(
        [first, second],
        last_sent={("reading", "first"): same, ("reading", "second"): same},
    )

    assert chosen is first


def test_no_notes_gives_none():
    assert choose_note([], last_sent={}) is None


def test_a_naive_last_send_is_read_as_utc_rather_than_raising():
    stale = note("stale")
    fresh = note("fresh")
    last_sent = {
        ("reading", "stale"): datetime(2026, 8, 1, 8, 30),
        ("reading", "fresh"): NOW - timedelta(days=1),
    }

    chosen = choose_note([fresh, stale], last_sent=last_sent)

    assert chosen is stale


def test_a_send_recorded_under_another_list_does_not_count_as_sent():
    other_list = note("shared", list_name="reading")
    sent_here = note("sent", list_name="reading")
    last_sent = {
        ("habits", "shared"): NOW - timedelta(days=90),
        ("reading", "sent"): NOW - timedelta(days=1),
    }

    chosen = choose_note([sent_here, other_list], last_sent=last_sent)

    assert chosen is other_list
