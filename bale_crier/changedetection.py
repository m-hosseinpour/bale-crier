"""The changedetection.io API, reduced to what the watcher needs.

The bot asks this API; it is never told. changedetection can push a notification
through Apprise, and the Apprise it ships with has no Bale plugin — its telegram
module is hardcoded to ``api.telegram.org`` — so that path would need a receiving
server of our own, which this project does not have and does not want. Polling the
loopback port keeps the bot a bot, and Bale reached from one module.

Two shapes come back: the watch list, whose ``last_changed`` is the watermark the
watcher compares across runs, and the diff of a watch's last change, which arrives
as one block of text with the segment placemarkers this module turns into ``+`` and
``-`` lines. That diff is the API's own per-snapshot diff, so a watch's ignore rules
(``ignore_text``) are not applied to it — it can carry a line the watch itself
considers noise.
"""

import re
from typing import NamedTuple

import requests

from .models import Watch

WATCHES_PATH = "/api/v1/watch"
DIFF_PATH = "/api/v1/watch/{uuid}/difference/previous/latest"
# `changesOnly` is what keeps the message to the lines that changed: without it the
# diff carries the unchanged lines around them as context.
DIFF_QUERY = "?format=text&no_markup=true&changesOnly=true"

# What a rendered line starts with, the way a patch reads. A changed segment is the old
# text and `changed_into` is what replaced it, so a rewritten line arrives as a `-` line
# and a `+` line.
CONTEXT = "  "
REMOVED = "- "
ADDED = "+ "

# The API wraps each changed segment in these; `no_markup` stops it turning them into
# HTML, not from emitting them. Longest first — `@changed_` is a prefix of
# `@changed_into_`.
_MARKER = re.compile(r"@(changed_into|changed|removed|added)_PLACEMARKER_(OPEN|CLOSED)")

_PREFIX = {
    "equal": CONTEXT,
    "added": ADDED,
    "removed": REMOVED,
    "changed": REMOVED,
    "changed_into": ADDED,
}

ACCESS_DENIED = (
    "changedetection کلید دسترسی را نپذیرفت (403)؛ کلید در تنظیمات خودش عوض شده است."
)


class WatchesRead(NamedTuple):
    """One look at the watch list. A failure is a value, never an exception."""

    watches: list[Watch] | None
    error: str


class DiffRead(NamedTuple):
    """The diff of a watch's last change.

    ``lines`` is ``None`` when the diff could not be read and empty when the watch
    has nothing to diff against (a single snapshot): the change is real either way,
    and only one of the two is a failure.
    """

    lines: list[str] | None
    error: str


def _request(
    url: str,
    *,
    key: str,
    timeout: int,
    allow: tuple[int, ...] = (200,),
) -> tuple[requests.Response | None, str]:
    try:
        response = requests.get(url, headers={"x-api-key": key}, timeout=timeout)
    except requests.RequestException as exc:
        return None, f"ارتباط با changedetection برقرار نشد: {exc}"
    if response.status_code == 403:
        # The one failure the owner can fix in a minute, so it says how.
        return None, ACCESS_DENIED
    if response.status_code not in allow:
        return None, f"changedetection پاسخ {response.status_code} داد."
    return response, ""


def epoch(value: object) -> int:
    """The API's epoch second as an int; 0 when it is not one, never a crash."""
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _segments(line: str) -> list[tuple[str, str]]:
    """One diff line split into ``(kind, text)`` by the API's placemarkers."""
    found: list[tuple[str, str]] = []
    kind = "equal"
    position = 0
    for marker in _MARKER.finditer(line):
        piece = line[position : marker.start()]
        if piece.strip():
            found.append((kind, piece.strip()))
        # The markers never nest: closing a segment returns the line to unchanged.
        kind = marker.group(1) if marker.group(2) == "OPEN" else "equal"
        position = marker.end()
    tail = line[position:]
    if tail.strip():
        found.append((kind, tail.strip()))
    return found


def diff_lines(text: str) -> list[str]:
    """The API's marked-up diff as patch-style lines: ``+`` added, ``-`` removed."""
    lines: list[str] = []
    for raw in text.splitlines():
        lines.extend(f"{_PREFIX[kind]}{segment}" for kind, segment in _segments(raw))
    return lines


def fetch_watches(*, base_url: str, key: str, timeout: int = 30) -> WatchesRead:
    url = f"{base_url.rstrip('/')}{WATCHES_PATH}"
    response, error = _request(url, key=key, timeout=timeout)
    if response is None:
        return WatchesRead(None, error)

    try:
        body = response.json()
    except ValueError as exc:
        return WatchesRead(None, f"پاسخ changedetection خوانا نبود: {exc}")
    if not isinstance(body, dict):
        return WatchesRead(None, "پاسخ changedetection شکل مورد انتظار را نداشت.")

    watches: list[Watch] = []
    for uuid, raw in body.items():
        if not isinstance(raw, dict):
            continue
        # The user's title is what the owner recognizes; the page's own title is the
        # fallback, and the URL is the last resort the bulletin itself handles.
        title = raw.get("title") or raw.get("page_title") or ""
        watches.append(
            Watch(
                uuid=str(uuid),
                title=str(title),
                url=str(raw.get("url") or ""),
                last_changed=epoch(raw.get("last_changed")),
            )
        )
    return WatchesRead(watches, "")


def fetch_diff(*, base_url: str, key: str, uuid: str, timeout: int = 30) -> DiffRead:
    url = f"{base_url.rstrip('/')}{DIFF_PATH.format(uuid=uuid)}{DIFF_QUERY}"
    response, error = _request(url, key=key, timeout=timeout, allow=(200, 404))
    if response is None:
        return DiffRead(None, error)
    # A 404 is a watch with one snapshot and nothing to diff against. The change is
    # real; only the text is unavailable, so it is not a failure.
    if response.status_code == 404:
        return DiffRead([], "")
    return DiffRead(diff_lines(response.text), "")
