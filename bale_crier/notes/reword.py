"""The reword prompt, and what goes out when the model cannot be reached.

The model expands the note into a short Persian paragraph — what the item is
worth and how to do it today — so the same item never arrives in the same words
twice; the earlier wordings are handed to it so it can avoid them. A failed call
is not a lost note (owner's ruling, 2026-10-17): the bulletin carries the note's
own text followed by one short line saying the rewording did not happen, and the
history then records what was actually sent.

There is no separate motivational sentence: the expansion carries the warm tone
inside it, so nothing is appended to it (owner's ruling, 2026-10-21).
"""

from collections.abc import Sequence

from .. import llm
from ..config import Settings
from ..llm import Llm
from ..models import Note

PREVIOUS_LIMIT = 3

SYSTEM_INSTRUCTION = (
    "تو یادداشت‌های شخصی صاحب ربات را به یک پیام فارسیِ تازه تبدیل می‌کنی. "
    "معنی یادداشت را نگه دار و آن را در یک پاراگراف سه تا چهار جمله‌ای بسط بده؛ "
    "خودِ یادداشت را عیناً تکرار نکن. "
    "بگو چرا این یادداشت به کار می‌آید و چطور می‌شود همین امروز انجامش داد؛ "
    "توضیح، تشبیه و مثال آزاد است. "
    "هیچ عدد، آمار، نقل‌قول یا رویدادی از خودت نساز و یادداشت را به واقعیتی بیرونی گره نزن. "
    "لحن گرم، صمیمی و انگیزه‌بخش باشد، نه دستوری و نه نصیحت‌گرانه. "
    "واژه‌ها و جمله‌بندی را تازه بساز و از تکرار متن‌های پیشین بپرهیز. "
    "نیم‌فاصله را با نویسهٔ واقعی بنویس، مثل «می‌شود»، «تجربه‌ها» و «بیشتر»، و پیشوند «نا» را چسبیده («ناموفق»). "
    "فقط متن پیام را بنویس؛ بدون مقدمه، بدون گیومه، بدون مارک‌داون، بدون عنوان و بدون شکستن خط."
)

REWORD_FAILED = "بازنویسی این بار انجام نشد"
NOTE_SENT = "متن اصلی یادداشت فرستاده می‌شود."


def build_messages(note: Note, previous: Sequence[str]) -> list[dict[str, str]]:
    """The system instruction plus the user turn, ready for ``complete``."""
    lines = ["یادداشت:", note.text]
    if previous:
        lines.append("")
        lines.append("پیش‌تر این متن‌ها فرستاده شده‌اند؛ آن‌ها را تکرار نکن و بازنویسی تازه‌ای بساز:")
        lines.extend(f"- {text}" for text in previous)
    lines.append("")
    lines.append("همین یادداشت را در یک پاراگراف سه تا چهار جمله‌ای، تازه، کاربردی و با لحنی گرم بسط بده.")
    return [
        {"role": "system", "content": SYSTEM_INSTRUCTION},
        {"role": "user", "content": "\n".join(lines)},
    ]


def fallback_text(note: Note, error: str) -> str:
    """The note's own text, then one short line saying the reword did not happen.

    ``error`` is the call's short code, and is named in parentheses when there is
    one — the owner sees why, and never loses the note to the failure.
    """
    code = f" ({error})" if error else ""
    return f"{note.text}\n\n{REWORD_FAILED}{code}؛ {NOTE_SENT}"


def reword(
    note: Note,
    previous: Sequence[str],
    *,
    settings: Settings,
    complete: Llm = llm.complete,
) -> str:
    """The model's rewording, or the note plus a failure line. Never raises.

    It cannot raise because ``complete`` cannot: every failure of the call is
    already a value by the time it returns here.
    """
    read = complete(
        build_messages(note, previous),
        key=settings.open_ai_api_key or "",
        model=settings.open_ai_model,
        base_url=settings.open_ai_base_url,
        timeout=settings.open_ai_timeout,
    )
    if read.text:
        return read.text
    return fallback_text(note, read.error)
