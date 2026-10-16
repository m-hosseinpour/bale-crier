"""The entry point: read the settings, run once, say what happened."""

import argparse
import sys
from datetime import datetime, timezone

from .config import ConfigError, load_settings
from .run import run_once


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bale_crier",
        description="Send every bulletin the producers have to the owner's Bale chat.",
    )
    try:
        parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    report = run_once(settings, now=datetime.now(timezone.utc))

    producers = "، ".join(report.producers) if report.producers else "هیچ"
    print(
        f"قاصد: {report.sent} پیام فرستاده شد و {report.failed} پیام ناموفق بود "
        f"(تولیدکننده‌ها: {producers})."
    )
    return 1 if report.failed else 0
