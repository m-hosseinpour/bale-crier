import requests

from bale_crier.bale import SEND_MESSAGE_PATH, send_message


class FakeResponse:
    def __init__(self, body):
        self._body = body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def stub_post(monkeypatch, response):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return response

    monkeypatch.setattr(requests, "post", fake_post)
    return captured


def test_request_is_a_post_to_the_send_message_url(monkeypatch):
    captured = stub_post(monkeypatch, FakeResponse({"ok": True, "result": {"message_id": 1}}))

    send_message("سلام", token="TOKEN", chat_id=7)

    assert captured["url"] == "https://tapi.bale.ai" + SEND_MESSAGE_PATH.format(token="TOKEN")
    assert captured["json"] == {"chat_id": 7, "text": "سلام"}
    assert captured["timeout"] == 30


def test_the_caller_can_override_base_url_and_timeout(monkeypatch):
    captured = stub_post(monkeypatch, FakeResponse({"ok": True}))

    send_message("سلام", token="TOKEN", chat_id=7, base_url="https://example.test", timeout=5)

    assert captured["url"] == "https://example.test" + SEND_MESSAGE_PATH.format(token="TOKEN")
    assert captured["timeout"] == 5


def test_ok_true_is_a_success(monkeypatch):
    stub_post(monkeypatch, FakeResponse({"ok": True, "result": {"message_id": 1}}))

    result = send_message("سلام", token="TOKEN", chat_id=7)

    assert result.ok is True
    assert result.error is None


def test_ok_false_carries_the_description_and_does_not_raise(monkeypatch):
    stub_post(monkeypatch, FakeResponse({"ok": False, "description": "chat not found"}))

    result = send_message("سلام", token="TOKEN", chat_id=7)

    assert result.ok is False
    # Exactly the description: an assertion that merely looks for the text would
    # also pass on the repr-of-body fallback, which contains it.
    assert result.error == "chat not found"


def test_a_transport_failure_is_a_failed_result(monkeypatch):
    def failing_post(url, json=None, timeout=None):
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr(requests, "post", failing_post)

    result = send_message("سلام", token="TOKEN", chat_id=7)

    assert result.ok is False
    assert "no route to host" in result.error


def test_a_non_json_body_is_a_failed_result(monkeypatch):
    stub_post(monkeypatch, FakeResponse(ValueError("Expecting value: line 1 column 1")))

    result = send_message("سلام", token="TOKEN", chat_id=7)

    assert result.ok is False
    assert result.error


def test_a_body_without_ok_is_a_failed_result(monkeypatch):
    stub_post(monkeypatch, FakeResponse(["unexpected"]))

    result = send_message("سلام", token="TOKEN", chat_id=7)

    assert result.ok is False
    assert result.error


def test_ok_false_without_a_description_still_carries_the_body(monkeypatch):
    """`description` is not a field the sibling project ever verified, so a body
    without it must still leave something readable behind."""
    stub_post(monkeypatch, FakeResponse({"ok": False, "error_code": 400}))

    result = send_message("سلام", token="TOKEN", chat_id=7)

    assert result.ok is False
    # The repr of the body, not a description — hence the brace.
    assert result.error.startswith("{")
    assert "400" in result.error
