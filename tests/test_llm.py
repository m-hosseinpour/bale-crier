import pytest
import requests

from bale_crier.llm import CHAT_PATH, LlmRead, complete

BASE = "https://api.avalai.ir/v1"
MESSAGES = [
    {"role": "system", "content": "دستور"},
    {"role": "user", "content": "متن"},
]


class FakeResponse:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def stub_post(monkeypatch, response):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return response

    monkeypatch.setattr(requests, "post", fake_post)
    return captured


def test_the_request_is_a_post_carrying_the_bearer_key_and_the_messages(monkeypatch):
    captured = stub_post(monkeypatch, FakeResponse({"choices": [{"message": {"content": "سلام"}}]}))

    complete(MESSAGES, key="SECRET", model="deepseek-v4-flash")

    assert captured["url"] == BASE + CHAT_PATH
    assert captured["headers"]["Authorization"] == "Bearer SECRET"
    assert captured["json"] == {"model": "deepseek-v4-flash", "messages": MESSAGES}
    assert captured["timeout"] == 30


def test_the_caller_can_override_base_url_and_timeout(monkeypatch):
    captured = stub_post(monkeypatch, FakeResponse({"choices": [{"message": {"content": "x"}}]}))

    complete(MESSAGES, key="k", model="m", base_url="https://example.test/v1", timeout=5)

    assert captured["url"] == "https://example.test/v1" + CHAT_PATH
    assert captured["timeout"] == 5


def test_a_200_with_content_is_the_text_and_no_error(monkeypatch):
    stub_post(monkeypatch, FakeResponse({"choices": [{"message": {"content": "سلام"}}]}))

    read = complete(MESSAGES, key="k", model="m")

    assert read.text == "سلام"
    assert read.error == ""


def test_padded_content_comes_back_stripped(monkeypatch):
    stub_post(monkeypatch, FakeResponse({"choices": [{"message": {"content": "  سلام\n"}}]}))

    assert complete(MESSAGES, key="k", model="m").text == "سلام"


@pytest.mark.parametrize("content", ["", "   ", ["not", "a", "string"], 7, None])
def test_content_that_is_empty_or_not_a_string_is_an_empty_completion(monkeypatch, content):
    stub_post(monkeypatch, FakeResponse({"choices": [{"message": {"content": content}}]}))

    read = complete(MESSAGES, key="k", model="m")

    assert read.text is None
    assert read.error == "empty completion"


def test_a_message_with_only_reasoning_content_is_an_empty_completion(monkeypatch):
    """The provider returns the model's private reasoning alongside the answer;
    reading that field would put it into the owner's chat."""
    stub_post(
        monkeypatch,
        FakeResponse({"choices": [{"message": {"reasoning_content": "let me think"}}]}),
    )

    read = complete(MESSAGES, key="k", model="m")

    assert read.text is None
    assert read.error == "empty completion"


def test_a_non_200_with_an_error_body_carries_the_status_and_not_the_prose(monkeypatch):
    stub_post(
        monkeypatch,
        FakeResponse(
            {
                "error": {
                    "message": "Invalid API key provided: sk-***. You can find your API key at ...",
                    "type": "invalid_request_error",
                    "code": "invalid_api_key",
                }
            },
            status_code=401,
        ),
    )

    read = complete(MESSAGES, key="k", model="m")

    assert read.text is None
    assert read.error == "HTTP 401"


def test_a_non_200_whose_body_is_not_json_carries_the_status(monkeypatch):
    stub_post(monkeypatch, FakeResponse(ValueError("Expecting value: line 1 column 1"), status_code=429))

    read = complete(MESSAGES, key="k", model="m")

    assert read.text is None
    assert read.error == "HTTP 429"


def test_a_transport_failure_is_a_transport_error(monkeypatch):
    def failing_post(url, headers=None, json=None, timeout=None):
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr(requests, "post", failing_post)

    read = complete(MESSAGES, key="k", model="m")

    assert read.text is None
    assert read.error == "transport error"


@pytest.mark.parametrize(
    "body",
    [
        ValueError("Expecting value: line 1 column 1"),  # not JSON at all
        ["unexpected"],  # JSON, but not an object
        {},  # no choices
        {"choices": []},  # an empty choices list
        {"choices": ["not a choice"]},  # choices[0] is not an object
        {"choices": [{}]},  # no message
        {"choices": [{"message": "not an object"}]},  # message is not an object
    ],
)
def test_a_200_whose_body_is_not_usable_is_an_unparsable_response(monkeypatch, body):
    stub_post(monkeypatch, FakeResponse(body))

    read = complete(MESSAGES, key="k", model="m")

    assert read.text is None
    assert read.error == "unparsable response"


def test_every_failure_path_returns_rather_than_raising(monkeypatch):
    """The caller is a run that must still record what happened, so a failure is a
    value on every path — never an exception."""
    responses = [
        FakeResponse({"choices": [{"message": {"content": "   "}}]}),
        FakeResponse({"choices": []}),
        FakeResponse(["unexpected"]),
        FakeResponse({"error": {"message": "nope"}}, status_code=500),
        FakeResponse(ValueError("Expecting value: line 1 column 1")),
    ]

    for response in responses:
        stub_post(monkeypatch, response)

        read = complete(MESSAGES, key="k", model="m")

        assert isinstance(read, LlmRead)
        assert read.text is None
        assert read.error
