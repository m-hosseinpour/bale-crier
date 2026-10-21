"""One reminder window, shared by the watchers that can repeat themselves.

The credit, disk and changedetection watchers all answer the same question about a
timestamp they wrote last time: has the window the owner set passed? The rule that
makes it safe is the same in all three, so it lives here once.
"""

from datetime import datetime, timedelta


def window_passed(last: object, *, now: datetime, hours: float) -> bool:
    """Whether ``hours`` have passed since ``last``, an ISO timestamp or nothing.

    A missing, corrupt or naive timestamp reads as "the window has passed": it costs
    one extra bulletin, never a crash and never a silence.
    """
    if not last:
        return True
    try:
        previous = datetime.fromisoformat(str(last))
        return now - previous >= timedelta(hours=hours)
    except (ValueError, TypeError):
        return True
