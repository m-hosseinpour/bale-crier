"""The AvalAI credit endpoint, parsed into numbers.

The numbers arrive as strings inside a package and as a number at the top level,
and the provider's shape is not guaranteed. Every container is checked before it
is used: a response that changed shape must produce "could not read it", never a
traceback, and never a verdict built on a container that was not actually read.
"""

import math
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import NamedTuple

import requests

from .models import CreditReport, Package

CREDIT_PATH = "/user/v1/credit"
DEFAULT_BASE_URL = "https://api.avalai.ir"
TIERS = ("daily", "weekly", "other")


class CreditRead(NamedTuple):
    """The outcome of one read. A failure is a value, never an exception."""

    report: CreditReport | None
    error: str


def tier_of(package: Mapping[str, object]) -> str:
    template = str(package.get("template_id") or "")
    name = str(package.get("name") or "")
    if template.startswith("d-") or "روزانه" in name:
        return "daily"
    if template.startswith("w-") or "هفتگی" in name:
        return "weekly"
    return "other"


def _number(value: object) -> float | None:
    # A bool is not a number here, and json.loads accepts a bare NaN or Infinity:
    # a balance of `nan` must not become a verdict.
    if isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse_timestamp(value: object) -> datetime | None:
    """One timestamp from the provider or from a watcher's memory, always aware.

    A naive timestamp is read as UTC: the provider sends UTC, and memory written by
    an older run may have lost the offset. An unreadable one is ``None``.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _parse_report(body: Mapping[str, object]) -> CreditReport:
    now = datetime.now(timezone.utc)
    sources = body.get("credit_sources")
    sources = sources if isinstance(sources, Mapping) else {}
    listed = sources.get("packages")
    listed = listed if isinstance(listed, list) else []

    packages: list[Package] = []
    for raw in listed:
        if not isinstance(raw, Mapping):
            continue
        end = parse_timestamp(raw.get("end_date"))
        remaining = _number(raw.get("remaining_irt"))
        packages.append(
            Package(
                tier=tier_of(raw),
                name=str(raw.get("name") or ""),
                remaining_irt=remaining,
                amount_irt=_number(raw.get("amount_irt")),
                end_date=end,
                spendable=(remaining or 0) > 0 and (end is None or end > now),
            )
        )

    # A tier's balance sums its spendable packages: two daily packages can coexist
    # when a new one is bought before the old one drains, and the provider's order
    # of consumption between them is not documented.
    tier_remaining = {
        tier: sum(
            package.remaining_irt or 0
            for package in packages
            if package.tier == tier and package.spendable
        )
        for tier in TIERS
    }
    active_tier = next((tier for tier in TIERS if tier_remaining[tier] > 0), None)
    main = _number(body.get("remaining_irt"))
    return CreditReport(
        main_balance_irt=main,
        packages=packages,
        tier_remaining=tier_remaining,
        active_tier=active_tier,
        active_remaining_irt=tier_remaining[active_tier] if active_tier else main,
    )


def fetch_report(
    *,
    key: str,
    timeout: int = 30,
    base_url: str = DEFAULT_BASE_URL,
) -> CreditRead:
    url = f"{base_url}{CREDIT_PATH}"
    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return CreditRead(None, f"ارتباط با AvalAI برقرار نشد: {exc}")

    try:
        body = response.json()
    except ValueError as exc:
        return CreditRead(None, f"پاسخ AvalAI خوانا نبود: {exc}")

    if not isinstance(body, dict):
        return CreditRead(None, "پاسخ AvalAI شکل مورد انتظار را نداشت.")

    return CreditRead(_parse_report(body), "")
