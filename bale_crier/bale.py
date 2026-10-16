"""The sender — the only module in the project that talks to Bale.

A second path to the API is a bug: the sender's failure handling is what keeps a
bad response from taking the run down before the history line is written.
"""

import requests

from .models import SendResult

BALE_API_BASE = "https://tapi.bale.ai"
SEND_MESSAGE_PATH = "/bot{token}/sendMessage"


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
