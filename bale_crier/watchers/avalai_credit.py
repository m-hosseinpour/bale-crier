"""The AvalAI credit watcher: a threshold with a latch, and a weekly package's end.

The number the threshold watches is whatever is paying right now — the active
tier's spendable balance, or the main balance when no package is live. A read that
cannot tell the number apart from zero is a failure, never a zero: the bulletin
says the reading failed. No bulletin advises a purchase; the threshold is the
owner's, not the bot's.

The second check is the weekly package's clock: a weekly package that still holds
money and is inside ``CRIER_CREDIT_EXPIRY_WARNING_HOURS`` of its end date speaks
once, naming what is left and when it goes. The announcement is remembered per
package, so the hourly check cannot turn into an hourly message.
"""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from ..config import Settings
from ..credit import CreditRead, fetch_report, parse_timestamp
from ..memory import WatcherMemory
from ..models import Bulletin, CreditReport
from .window import window_passed

CreditReader = Callable[..., CreditRead]

TIER_LABELS = {
    "daily": "بستهٔ روزانه",
    "weekly": "بستهٔ هفتگی",
    "other": "بستهٔ ناشناخته",
}
MAIN_LABEL = "اعتبار اصلی"

# Only a weekly package has an end worth an early word: a daily package's whole life
# is one day, so a day's warning would be on from the moment it was bought.
EXPIRY_TIER = "weekly"


class Expiring(NamedTuple):
    """One weekly package inside the warning window: what it is, and what is left.

    ``remaining`` is ``None`` when the provider's number could not be read: the
    package still lapses, and "I cannot tell" must not turn into "it is empty".
    """

    name: str
    end: datetime
    remaining: float | None


UNKNOWN_TEXT = (
    "خواندن اعتبار از AvalAI ممکن نشد و نمی‌دانم چقدر مانده است. "
    "این فقط یک خواندن ناموفق بود، نه خبری دربارهٔ مقدار اعتبار."
)


def _amount(value: float) -> str:
    return f"{value:,.0f}"


def _subject(name: str) -> str:
    """The package's own name, quoted, or a plain word when the provider gave none."""
    return f"«{name}»" if name else "بدون نام"


def _span(left: timedelta) -> str:
    # Floored, never rounded up: "23 ساعت" with 23h59m left is honest, "24 ساعت" is not.
    seconds = max(0, int(left.total_seconds()))
    if seconds >= 3600:
        return f"{seconds // 3600} ساعت"
    if seconds >= 60:
        return f"{seconds // 60} دقیقه"
    return "کمتر از یک دقیقه"


def _announced(raw: object, now: datetime) -> list[dict[str, str]]:
    """The announcements still worth keeping: one per package that has not lapsed.

    Anything unreadable is dropped, which costs one extra bulletin and never a
    crash — the same rule the latch and the window follow.
    """
    if not isinstance(raw, list):
        return []
    kept: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        end = parse_timestamp(item.get("end_date"))
        if not isinstance(name, str) or end is None or end <= now:
            continue
        kept.append({"name": name, "end_date": end.isoformat()})
    return kept


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

        bulletins = self._expiry_bulletins(report, now)
        if remaining >= self._settings.credit_threshold_irt:
            self._arm()
        elif self._armed():
            self._remember(armed=False)
            bulletins.append(self._alert(remaining, report))
        return bulletins

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

    def _expiry_bulletins(self, report: CreditReport, now: datetime) -> list[Bulletin]:
        due = self._due(report, now)
        state = self._memory.get(self.name)
        raw = state.get("expiry_announced")
        announced = _announced(raw, now)
        known = {(item["name"], item["end_date"]) for item in announced}
        fresh = [
            package
            for package in due
            if (package.name, package.end.isoformat()) not in known
        ]
        if not fresh:
            # Forgetting a package that has lapsed is tidying, not news — and a quiet
            # run writes nothing at all, so it stays invisible on disk too.
            if isinstance(raw, list) and raw != announced:
                self._remember(armed=self._armed(), announced=announced)
            return []
        self._remember(
            armed=self._armed(),
            announced=announced
            + [
                {"name": package.name, "end_date": package.end.isoformat()}
                for package in fresh
            ],
        )
        return [self._expiry_alert(fresh, now)]

    def _due(self, report: CreditReport, now: datetime) -> list[Expiring]:
        window = timedelta(hours=self._settings.credit_expiry_warning_hours)
        due: list[Expiring] = []
        for package in report.packages:
            if package.tier != EXPIRY_TIER or package.end_date is None:
                continue
            remaining = package.remaining_irt
            left = package.end_date - now
            # An empty pot lapsing is not news, and a lapsed one is already past. An
            # unreadable balance still lapses, so it is announced without its amount.
            empty = remaining is not None and remaining <= 0
            if empty or left <= timedelta(0) or left >= window:
                continue
            due.append(Expiring(package.name, package.end_date, remaining))
        return due

    def _expiry_alert(self, packages: list[Expiring], now: datetime) -> Bulletin:
        if len(packages) == 1:
            package = packages[0]
            money = (
                f"و {_amount(package.remaining)} تومان در آن مانده است."
                if package.remaining is not None
                else "و مقدار باقی‌مانده‌اش خوانده نشد."
            )
            text = (
                f"بستهٔ هفتگی {_subject(package.name)} تا {_span(package.end - now)} دیگر "
                f"منقضی می‌شود {money}"
            )
        else:
            furthest = max(package.end for package in packages) - now
            lines = "\n".join(
                f"{_subject(package.name)} — تا {_span(package.end - now)} دیگر، "
                + (
                    f"{_amount(package.remaining)} تومان"
                    if package.remaining is not None
                    else "مقدار باقی‌مانده خوانده نشد"
                )
                for package in packages
            )
            text = (
                f"{len(packages)} بستهٔ هفتگی تا {_span(furthest)} دیگر منقضی می‌شوند:\n{lines}"
            )
        return Bulletin(kind="alert", text=text)

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
        return window_passed(last, now=now, hours=self._settings.credit_unknown_alert_hours)

    def _remember(
        self,
        *,
        armed: bool,
        unknown_at: datetime | None = None,
        announced: list[dict[str, str]] | None = None,
    ) -> None:
        state = self._memory.get(self.name)
        self._memory.set(
            self.name,
            {
                "armed": armed,
                "last_unknown_alert": (
                    unknown_at.isoformat() if unknown_at is not None else state.get("last_unknown_alert")
                ),
                "expiry_announced": (
                    announced if announced is not None else state.get("expiry_announced", [])
                ),
            },
        )
