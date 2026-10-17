"""The AvalAI chat call, reduced to the text or a short error code.

The caller owns the prompt; this module is only the transport, and it never reads
the settings itself. ``content`` is read by name: this provider also returns
``reasoning_content`` on the message, and falling back to it would put the
model's private reasoning into the owner's chat.
"""

from collections.abc import Callable
from typing import NamedTuple

import requests

CHAT_PATH = "/chat/completions"
DEFAULT_BASE_URL = "https://api.avalai.ir/v1"


class LlmRead(NamedTuple):
    """The outcome of one completion. A failure is a value, never an exception."""

    text: str | None
    error: str


Llm = Callable[..., LlmRead]


def complete(
    messages: list[dict[str, str]],
    *,
    key: str,
    model: str,
    base_url: str = DEFAULT_BASE_URL,
    timeout: int = 30,
) -> LlmRead:
    url = f"{base_url}{CHAT_PATH}"
    try:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "messages": messages},
            timeout=timeout,
        )
    except requests.RequestException:
        return LlmRead(None, "transport error")

    # The provider's error body is long English prose, and the code is embedded
    # in a Persian bulletin: the status alone is what belongs there.
    if response.status_code != 200:
        return LlmRead(None, f"HTTP {response.status_code}")

    try:
        body = response.json()
    except ValueError:
        return LlmRead(None, "unparsable response")

    if not isinstance(body, dict):
        return LlmRead(None, "unparsable response")

    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return LlmRead(None, "unparsable response")
    first = choices[0]
    if not isinstance(first, dict):
        return LlmRead(None, "unparsable response")

    message = first.get("message")
    if not isinstance(message, dict):
        return LlmRead(None, "unparsable response")

    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        return LlmRead(None, "empty completion")

    return LlmRead(content.strip(), "")
