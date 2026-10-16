"""The entry point: read the settings, run once, say what happened."""

import argparse
import sys
from datetime import datetime, timezone

from .config import ConfigError, load_settings
from .run import KNOWN_PRODUCERS, run_once


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bale_crier",
        description="Send every bulletin the producers have to the owner's Bale chat.",
    )
    parser.add_argument(
        "--only",
        action="append",
        choices=KNOWN_PRODUCERS,
        metavar="NAME",
        help="run only this producer; repeatable. The credit watcher has a timer of its own.",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.only and "credit" in args.only and not settings.avalai_api_key:
        print(
            "ناظر اعتبار بدون کلید اجرا نمی‌شود: CRIER_AVALAI_API_KEY تنظیم نشده است.",
            file=sys.stderr,
        )

    report = run_once(settings, now=datetime.now(timezone.utc), only=args.only)

    producers = "، ".join(report.producers) if report.producers else "هیچ"
    print(
        f"قاصد: {report.sent} پیام فرستاده شد و {report.failed} پیام ناموفق بود "
        f"(تولیدکننده‌ها: {producers})."
    )
    return 1 if report.failed else 0
