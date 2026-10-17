from pathlib import Path

from bale_crier.models import Bulletin, Note
from bale_crier.notes.lists import read_notes


def write(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def test_one_file_with_two_notes_gives_two_notes_in_file_order(tmp_path):
    write(
        tmp_path,
        "reading.md",
        "## reading-1\nهر روز یک صفحه کتاب بخوان\n\n## reading-2\nهر هفته یک کتاب تازه شروع کن\n",
    )

    notes = read_notes(tmp_path)

    assert [note.id for note in notes] == ["reading-1", "reading-2"]
    assert [note.text for note in notes] == [
        "هر روز یک صفحه کتاب بخوان",
        "هر هفته یک کتاب تازه شروع کن",
    ]
    assert [note.list_name for note in notes] == ["reading", "reading"]


def test_a_multi_line_body_keeps_its_breaks_and_is_stripped_at_both_ends(tmp_path):
    write(tmp_path, "reading.md", "## reading-1\n\n   کتاب‌ها را می‌خوانم\n\nخط دوم\n\n")

    notes = read_notes(tmp_path)

    assert notes[0].text == "کتاب‌ها را می‌خوانم\n\nخط دوم"


def test_a_hash_title_is_ignored_and_a_subheading_stays_in_the_body(tmp_path):
    write(
        tmp_path,
        "reading.md",
        "# فهرست خواندن\n\n## reading-1\nمتن اصلی\n### زیربخش\nمتن زیربخش\n",
    )

    notes = read_notes(tmp_path)

    assert [note.id for note in notes] == ["reading-1"]
    assert notes[0].text == "متن اصلی\n### زیربخش\nمتن زیربخش"


def test_a_note_with_an_empty_body_is_skipped(tmp_path):
    write(tmp_path, "reading.md", "## reading-1\n\n## reading-2\nمتن دوم\n")

    notes = read_notes(tmp_path)

    assert [note.id for note in notes] == ["reading-2"]


def test_a_duplicate_id_keeps_the_first(tmp_path):
    write(tmp_path, "reading.md", "## reading-1\nنخست\n## reading-1\nدوم\n")

    notes = read_notes(tmp_path)

    assert len(notes) == 1
    assert notes[0].text == "نخست"


def test_an_empty_headed_note_does_not_claim_the_id(tmp_path):
    """Nothing to reword is not a note, so a later heading with the same id and a
    body is still the one that goes."""
    write(tmp_path, "reading.md", "## reading-1\n\n## reading-1\nمتن دوم\n")

    notes = read_notes(tmp_path)

    assert [note.id for note in notes] == ["reading-1"]
    assert notes[0].text == "متن دوم"


def test_two_files_come_back_in_file_name_order_and_the_same_id_is_two_notes(tmp_path):
    write(tmp_path, "zulu.md", "## shared\nاز فایل دوم\n")
    write(tmp_path, "alpha.md", "## shared\nاز فایل اول\n")

    notes = read_notes(tmp_path)

    assert [note.list_name for note in notes] == ["alpha", "zulu"]
    assert [note.text for note in notes] == ["از فایل اول", "از فایل دوم"]
    assert len({(note.list_name, note.id) for note in notes}) == 2


def test_a_non_markdown_file_is_ignored(tmp_path):
    write(tmp_path, "notes.txt", "## reading-1\nمتن فایل متنی\n")
    write(tmp_path, "reading.md", "## reading-1\nمتن فایل مارک‌داون\n")

    notes = read_notes(tmp_path)

    assert len(notes) == 1
    assert notes[0].list_name == "reading"


def test_a_missing_directory_is_empty_and_raises_nothing(tmp_path):
    assert read_notes(tmp_path / "absent") == []


def test_a_path_that_is_a_file_is_empty_and_raises_nothing(tmp_path):
    path = write(tmp_path, "reading.md", "## reading-1\nمتن\n")

    assert read_notes(path) == []


def test_an_undecodable_file_is_skipped_and_the_others_still_read(tmp_path):
    (tmp_path / "broken.md").write_bytes(b"## reading-1\n\xff\xfe\x00\n")
    write(tmp_path, "reading.md", "## reading-1\nمتن سالم\n")

    notes = read_notes(tmp_path)

    assert [note.list_name for note in notes] == ["reading"]
    assert notes[0].text == "متن سالم"


def test_note_round_trips():
    note = Note(list_name="a", id="b", text="c")

    assert note.text == "c"


def test_bulletin_carries_list_name_and_defaults_to_none():
    assert Bulletin(kind="note", text="x", note_id="i", list_name="l").list_name == "l"
    assert Bulletin(kind="note", text="x", note_id="i").list_name is None
