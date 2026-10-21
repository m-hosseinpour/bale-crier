"""The entry point: read the settings, run once, say what happened."""

import argparse
import sys
from datetime import datetime, timezone

from .config import ConfigError, load_settings
from .run import CHANGEDETECTION, CREDIT, KNOWN_PRODUCERS, NEWS, NOTE, run_once


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
        help=(
            "run only this producer; repeatable. The credit, disk and "
            "changedetection watchers and the news digest have timers of their own."
        ),
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

    # A producer that cannot be built must not be a silent gap: without a word, a
    # missing key or a missing directory looks exactly like a quiet day. A smoke run
    # is the exception — it asks no producer for notes, so warning about them there
    # would be a false alarm on the very deploy check the warning is for.
    notes_wanted = (NOTE in args.only) if args.only else not settings.smoke
    if notes_wanted and not settings.open_ai_api_key:
        print(
            "بازنویسی یادداشت‌ها بدون کلید مدل ممکن نیست: "
            "CRIER_OPEN_AI_API_KEY (یا CRIER_AVALAI_API_KEY) تنظیم نشده است.",
            file=sys.stderr,
        )
    if notes_wanted and not settings.lists_dir.is_dir():
        print(
            f"پوشهٔ لیست‌ها پیدا نشد: {settings.lists_dir}؛ یادداشتی فرستاده نمی‌شود.",
            file=sys.stderr,
        )
    if args.only and CREDIT in args.only and not settings.avalai_api_key:
        print(
            "ناظر اعتبار بدون کلید اجرا نمی‌شود: CRIER_AVALAI_API_KEY تنظیم نشده است.",
            file=sys.stderr,
        )
    if args.only and NEWS in args.only and not settings.open_ai_api_key:
        print(
            "خبرنامه بدون کلید مدل ساخته نمی\u200cشود: "
            "CRIER_OPEN_AI_API_KEY (یا CRIER_AVALAI_API_KEY) تنظیم نشده است.",
            file=sys.stderr,
        )
    if args.only and CHANGEDETECTION in args.only and not settings.changedetection_api_key:
        print(
            "ناظر تغییر‌ها بدون کلید اجرا نمی\u200cشود: "
            "CRIER_CHANGEDETECTION_API_KEY تنظیم نشده است.",
            file=sys.stderr,
        )

    report = run_once(settings, now=datetime.now(timezone.utc), only=args.only)

    producers = "، ".join(report.producers) if report.producers else "هیچ"
    print(
        f"قاصد: {report.sent} پیام فرستاده شد و {report.failed} پیام ناموفق بود "
        f"(تولیدکننده‌ها: {producers})."
    )
    return 1 if report.failed else 0
