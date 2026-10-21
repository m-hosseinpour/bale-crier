"""Numbers as the owner reads them.

Persian text counts in Persian digits (``۳ صفحه``), while the numbers that are data —
money, GiB, a model name, a URL — stay Latin, because those are values the owner copies
or compares rather than reads as prose.
"""

_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def digits(value: int) -> str:
    """``value`` written with Persian digits."""
    return str(value).translate(_DIGITS)
