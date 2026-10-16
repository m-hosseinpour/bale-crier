"""The AvalAI credit watcher: a threshold with a latch.

The number it watches is whatever is paying right now — the active tier's
spendable balance, or the main balance when no package is live. A read that
cannot tell the number apart from zero is a failure, never a zero: the bulletin
says the reading failed. Neither bulletin advises a purchase; the threshold is
the owner's, not the bot's.
"""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from ..config import Settings
from ..credit import CreditRead, fetch_report
from ..memory import WatcherMemory
from ..models import Bulletin, CreditReport

CreditReader = Callable[..., CreditRead]

TIER_LABELS = {
    "daily": "بستهٔ روزانه",
    "weekly": "بستهٔ هفتگی",
    "other": "بستهٔ ناشناخته",
}
MAIN_LABEL = "اعتبار اصلی"

UNKNOWN_TEXT = (
    "خواندن اعتبار از AvalAI ممکن نشد و نمی‌دانم چقدر مانده است. "
    "این فقط یک خواندن ناموفق بود، نه خبری دربارهٔ مقدار اعتبار."
)


def _amount(value: float) -> str:
    return f"{value:,.0f}"


class CreditWatcher:
    name = "credit"
    own_timer = True

    def __init__(
        self,
        settings: Settings,
        memory: WatcherMemory,
        read: CreditReader = fetch_report,
    ) -> None:
        self._settings = settings
        self._memory = memory
        self._read = read

    def produce(self, now: datetime) -> list[Bulletin]:
        now = now.astimezone(timezone.utc)
        read = self._read(key=self._settings.avalai_api_key, timeout=self._settings.http_timeout)
        report = read.report
        # `None` here is "could not read it", not a zero balance.
        remaining = report.active_remaining_irt if report is not None else None
        if remaining is None:
            return self._unreadable(now, read.error)

        if remaining >= self._settings.credit_threshold_irt:
            self._arm()
            return []

        if not self._armed():
            return []
        self._remember(armed=False)
        return [self._alert(remaining, report)]

    def _alert(self, remaining: float, report: CreditReport) -> Bulletin:
        label = TIER_LABELS.get(report.active_tier or "", MAIN_LABEL)
        threshold = self._settings.credit_threshold_irt
        return Bulletin(
            kind="alert",
            text=(
                f"اعتبار از آستانه پایین‌تر آمد: {label} {_amount(remaining)} تومان مانده "
                f"و آستانه {_amount(threshold)} تومان است."
            ),
        )

    def _unreadable(self, now: datetime, error: str) -> list[Bulletin]:
        state = self._memory.get(self.name)
        if not self._window_passed(state.get("last_unknown_alert"), now):
            return []
        # The latch is carried over untouched: a failed read must not consume the
        # crossing it could not see.
        self._remember(armed=state.get("armed", True), unknown_at=now)
        text = f"{UNKNOWN_TEXT}\n\n{error}" if error else UNKNOWN_TEXT
        return [Bulletin(kind="alert", text=text)]

    def _armed(self) -> bool:
        return self._memory.get(self.name).get("armed", True)

    def _arm(self) -> None:
        if not self._armed():
            self._remember(armed=True)

    def _window_passed(self, last: object, now: datetime) -> bool:
        if not last:
            return True
        try:
            previous = datetime.fromisoformat(str(last))
            return now - previous >= timedelta(hours=self._settings.credit_unknown_alert_hours)
        except (ValueError, TypeError):
            # A corrupt or naive timestamp costs one extra bulletin, never a crash.
            return True

    def _remember(self, *, armed: bool, unknown_at: datetime | None = None) -> None:
        state = self._memory.get(self.name)
        self._memory.set(
            self.name,
            {
                "armed": armed,
                "last_unknown_alert": (
                    unknown_at.isoformat() if unknown_at is not None else state.get("last_unknown_alert")
                ),
            },
        )
