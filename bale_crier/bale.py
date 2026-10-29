"""The sender — the only module in the project that talks to Bale.

A second path to the API is a bug: the sender's failure handling is what keeps a
bad response from taking the run down before the history line is written.

Formatting is Bale's rule too, so the one thing every message needs to know about it
lives here: Bale renders every message as Markdown, with no `parse_mode` to ask for,
and ``markdown_link`` builds a link a message can carry without breaking.
"""

import requests

from .models import SendResult

BALE_API_BASE = "https://tapi.bale.ai"
SEND_MESSAGE_PATH = "/bot{token}/sendMessage"


def markdown_link(label: str, url: str, *, fallback: str) -> str:
    """``[label](url)``, safe to put in a message.

    Bale formats every message as Markdown, so an address can ride under a name
    instead of filling the line — which matters when the address is a three-hundred
    character redirect.

    A ``]`` in the label would close it early and spill the rest of the line as text,
    so brackets are dropped from the label: a name is a name with or without them.
    Parentheses in the address end it the same way, and percent-encoding those two
    leaves the same address, one a browser still opens. Markdown has no link without
    a label, so a label that cleans down to nothing — an empty source name, a name of
    nothing but brackets — becomes the caller's ``fallback`` instead.
    """
    clean = label.replace("[", "").replace("]", "").strip() or fallback
    return f"[{clean}]({url.replace('(', '%28').replace(')', '%29')})"


def send_message(
    text: str,
    *,
    token: str,
    chat_id: int,
    base_url: str = BALE_API_BASE,
    timeout: int = 30,
) -> SendResult:
    url = f"{base_url}{SEND_MESSAGE_PATH.format(token=token)}"
    try:
        response = requests.post(
            url,
            json={"chat_id": chat_id, "text": text},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return SendResult(ok=False, error=f"ارتباط با بله برقرار نشد: {exc}")

    try:
        body = response.json()
    except ValueError as exc:
        return SendResult(ok=False, error=f"پاسخ بله خوانا نبود: {exc}")

    if not isinstance(body, dict) or not body.get("ok"):
        description = body.get("description") if isinstance(body, dict) else None
        return SendResult(ok=False, error=str(description or repr(body)[:200]))

    return SendResult(ok=True)
