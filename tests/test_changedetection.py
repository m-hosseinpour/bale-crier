import requests

from bale_crier.changedetection import (
    ACCESS_DENIED,
    diff_lines,
    fetch_diff,
    fetch_watches,
)

BASE = "http://127.0.0.1:5005"
UUID = "7950b31a-25eb-459b-b336-9f4f2affc2dc"


class FakeResponse:
    def __init__(self, body=None, *, status_code=200, text=""):
        self._body = body
        self.status_code = status_code
        self.text = text

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def stub(monkeypatch, response):
    """One recorded call, so the URL and the header can be asserted too."""
    calls = []

    def get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(requests, "get", get)
    return calls


def test_the_watch_list_is_parsed_into_what_a_run_compares(monkeypatch):
    stub(
        monkeypatch,
        FakeResponse(
            {
                UUID: {
                    "title": "",
                    "page_title": None,
                    "url": "https://example.test/models",
                    "last_changed": 1792247965,
                    "last_checked": 1792582781,
                }
            }
        ),
    )

    read = fetch_watches(base_url=BASE, key="k")

    assert read.error == ""
    assert len(read.watches) == 1
    watch = read.watches[0]
    assert watch.uuid == UUID
    assert watch.url == "https://example.test/models"
    assert watch.last_changed == 1792247965


def test_the_page_title_stands_in_when_the_owner_set_none(monkeypatch):
    stub(monkeypatch, FakeResponse({UUID: {"page_title": "Models", "url": "u", "last_changed": 5}}))

    watch = fetch_watches(base_url=BASE, key="k").watches[0]

    assert watch.title == "Models"


def test_a_watch_that_never_changed_reads_as_zero(monkeypatch):
    stub(monkeypatch, FakeResponse({UUID: {"last_changed": None}}))

    assert fetch_watches(base_url=BASE, key="k").watches[0].last_changed == 0


def test_a_garbage_last_changed_reads_as_zero_rather_than_a_crash(monkeypatch):
    stub(monkeypatch, FakeResponse({UUID: {"last_changed": "yesterday"}}))

    assert fetch_watches(base_url=BASE, key="k").watches[0].last_changed == 0


def test_the_request_carries_the_key_and_the_local_base_url(monkeypatch):
    calls = stub(monkeypatch, FakeResponse({}))

    fetch_watches(base_url=BASE, key="secret", timeout=9)

    assert calls[0]["url"] == "http://127.0.0.1:5005/api/v1/watch"
    assert calls[0]["headers"] == {"x-api-key": "secret"}
    assert calls[0]["timeout"] == 9


def test_a_trailing_slash_on_the_base_url_does_not_double_the_path(monkeypatch):
    calls = stub(monkeypatch, FakeResponse({}))

    fetch_watches(base_url="http://127.0.0.1:5005/", key="k")

    assert calls[0]["url"] == "http://127.0.0.1:5005/api/v1/watch"


def test_a_refused_key_says_what_to_fix(monkeypatch):
    stub(monkeypatch, FakeResponse(status_code=403))

    read = fetch_watches(base_url=BASE, key="k")

    assert read.watches is None
    assert read.error == ACCESS_DENIED


def test_another_status_names_the_code(monkeypatch):
    stub(monkeypatch, FakeResponse(status_code=500))

    read = fetch_watches(base_url=BASE, key="k")

    assert read.watches is None
    assert "500" in read.error


def test_an_unreachable_api_is_a_value_not_an_exception(monkeypatch):
    stub(monkeypatch, requests.ConnectionError("refused"))

    read = fetch_watches(base_url=BASE, key="k")

    assert read.watches is None
    assert "برقرار نشد" in read.error


def test_a_body_that_is_not_json_says_so(monkeypatch):
    stub(monkeypatch, FakeResponse(ValueError("no json")))

    read = fetch_watches(base_url=BASE, key="k")

    assert read.watches is None
    assert "خوانا نبود" in read.error


def test_a_body_that_is_not_an_object_says_so(monkeypatch):
    stub(monkeypatch, FakeResponse([{"uuid": UUID}]))

    assert fetch_watches(base_url=BASE, key="k").watches is None


def test_an_added_line_and_a_removed_line_keep_their_direction():
    body = (
        '@removed_PLACEMARKER_OPEN    "old-model"@removed_PLACEMARKER_CLOSED\n'
        '@added_PLACEMARKER_OPEN    "new-model"@added_PLACEMARKER_CLOSED'
    )

    assert diff_lines(body) == ['- "old-model"', '+ "new-model"']


def test_a_replaced_value_arrives_as_the_old_line_then_the_new_one():
    """`changed` is the text that went away and `changed_into` is what replaced it."""
    body = (
        '@changed_PLACEMARKER_OPEN    "space-bunny-free"@changed_PLACEMARKER_CLOSED '
        '@changed_into_PLACEMARKER_OPEN    "minimax-free"@changed_into_PLACEMARKER_CLOSED'
    )

    assert diff_lines(body) == ['- "space-bunny-free"', '+ "minimax-free"']


def test_a_line_can_carry_unchanged_text_and_a_change():
    body = (
        '    "a-free",@added_PLACEMARKER_OPEN "b-free",@added_PLACEMARKER_CLOSED'
    )

    assert diff_lines(body) == ['  "a-free",', '+ "b-free",']


def test_the_diff_asks_for_the_changed_lines_only(monkeypatch):
    calls = stub(monkeypatch, FakeResponse(text=""))

    fetch_diff(base_url=BASE, key="k", uuid=UUID)

    assert f"/api/v1/watch/{UUID}/difference/previous/latest" in calls[0]["url"]
    assert "changesOnly=true" in calls[0]["url"]
    assert "no_markup=true" in calls[0]["url"]


def test_a_watch_with_one_snapshot_has_no_diff_and_no_failure(monkeypatch):
    stub(monkeypatch, FakeResponse(status_code=404))

    read = fetch_diff(base_url=BASE, key="k", uuid=UUID)

    assert read.lines == []
    assert read.error == ""


def test_a_diff_that_cannot_be_read_is_a_failure(monkeypatch):
    stub(monkeypatch, FakeResponse(status_code=403))

    read = fetch_diff(base_url=BASE, key="k", uuid=UUID)

    assert read.lines is None
    assert read.error == ACCESS_DENIED


def test_an_empty_diff_body_is_an_empty_list_not_a_failure(monkeypatch):
    stub(monkeypatch, FakeResponse(text=""))

    assert fetch_diff(base_url=BASE, key="k", uuid=UUID).lines == []
