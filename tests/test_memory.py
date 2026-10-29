import json

from bale_crier.memory import WatcherMemory


def test_get_on_a_name_that_never_wrote_is_empty(tmp_path):
    memory = WatcherMemory.load(tmp_path / "watchers.json")

    assert memory.get("credit") == {}


def test_set_then_save_then_load_round_trips(tmp_path):
    path = tmp_path / "data" / "watchers.json"
    memory = WatcherMemory.load(path)
    memory.set("credit", {"armed": False, "last_unknown_alert": None})
    memory.save()

    assert WatcherMemory.load(path).get("credit") == {"armed": False, "last_unknown_alert": None}


def test_a_missing_file_loads_empty(tmp_path):
    assert WatcherMemory.load(tmp_path / "absent.json").as_dict() == {}


def test_invalid_json_loads_empty(tmp_path):
    path = tmp_path / "watchers.json"
    path.write_text("{not json at all", encoding="utf-8")

    assert WatcherMemory.load(path).as_dict() == {}


def test_json_that_is_not_an_object_loads_empty(tmp_path):
    path = tmp_path / "watchers.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")

    assert WatcherMemory.load(path).as_dict() == {}


def test_a_blob_that_is_not_an_object_is_dropped(tmp_path):
    path = tmp_path / "watchers.json"
    path.write_text(json.dumps({"credit": "not an object"}), encoding="utf-8")

    assert WatcherMemory.load(path).get("credit") == {}


def test_save_creates_the_parent_directory(tmp_path):
    path = tmp_path / "nested" / "deeper" / "watchers.json"
    memory = WatcherMemory.load(path)
    memory.set("credit", {"armed": True})

    memory.save()

    assert path.is_file()


def test_save_leaves_no_tmp_neighbour_and_writes_the_new_content(tmp_path):
    path = tmp_path / "watchers.json"
    path.write_text(json.dumps({"credit": {"armed": False}}), encoding="utf-8")
    memory = WatcherMemory.load(path)
    memory.set("credit", {"armed": True})

    memory.save()

    assert json.loads(path.read_text(encoding="utf-8")) == {"credit": {"armed": True}}
    assert list(path.parent.glob("*.tmp")) == []


def test_save_replaces_the_file_rather_than_truncating_it(tmp_path):
    """A rename gives the file a new inode; a truncate-then-write keeps it."""
    path = tmp_path / "watchers.json"
    memory = WatcherMemory.load(path)
    memory.set("credit", {"armed": True})
    memory.save()
    first = path.stat().st_ino

    memory.set("credit", {"armed": False})
    memory.save()

    assert path.stat().st_ino != first


def test_a_save_with_nothing_to_write_creates_no_file(tmp_path):
    path = tmp_path / "watchers.json"

    WatcherMemory.load(path).save()

    assert not path.exists()


def test_set_on_one_name_leaves_another_name_alone(tmp_path):
    memory = WatcherMemory.load(tmp_path / "watchers.json")

    memory.set("credit", {"armed": True})
    memory.set("other", {"count": 2})

    assert memory.get("credit") == {"armed": True}
    assert memory.get("other") == {"count": 2}


def test_two_names_survive_a_save_and_a_load(tmp_path):
    path = tmp_path / "watchers.json"
    memory = WatcherMemory.load(path)
    memory.set("credit", {"armed": True})
    memory.set("other", {"count": 2})

    memory.save()

    loaded = WatcherMemory.load(path)
    assert loaded.get("credit") == {"armed": True}
    assert loaded.get("other") == {"count": 2}


def test_a_save_with_nothing_changed_does_not_touch_the_file(tmp_path):
    path = tmp_path / "watchers.json"
    seed = WatcherMemory.load(path)
    seed.set("credit", {"armed": True})
    seed.save()
    before = path.stat().st_ino

    WatcherMemory.load(path).save()

    assert path.stat().st_ino == before


def test_a_run_that_changes_nothing_leaves_another_runs_write_alone(tmp_path):
    """The note run shares this file but owns no credit watcher, so it must not
    write back the latch it loaded: a re-arm the hourly run recorded in between
    would be undone, and the next crossing swallowed."""
    path = tmp_path / "watchers.json"
    seed = WatcherMemory.load(path)
    seed.set("credit", {"armed": False})
    seed.save()

    note = WatcherMemory.load(path)
    hourly = WatcherMemory.load(path)
    hourly.set("credit", {"armed": True})
    hourly.save()

    note.save()

    assert WatcherMemory.load(path).get("credit") == {"armed": True}


def test_a_run_writing_one_name_leaves_another_runs_name_alone(tmp_path):
    path = tmp_path / "watchers.json"
    seed = WatcherMemory.load(path)
    seed.set("credit", {"armed": False})
    seed.save()

    one = WatcherMemory.load(path)
    other = WatcherMemory.load(path)
    one.set("credit", {"armed": True})
    one.save()

    other.set("something", {"count": 1})
    other.save()

    loaded = WatcherMemory.load(path)
    assert loaded.get("credit") == {"armed": True}
    assert loaded.get("something") == {"count": 1}
