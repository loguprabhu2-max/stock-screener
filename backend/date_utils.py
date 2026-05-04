"""Flexible date parsing and uniform display formatting.

Goal:
  - Accept multiple input formats from CSVs (DD-MM-YYYY, DD/MM/YYYY,
    YYYY-MM-DD, DD.MM.YYYY, DD-Mon-YYYY, etc.).
  - Always show dates on screen as 'DD MM YYYY' (with spaces).
  - Database stays as standard SQL DATE (unchanged).

For ambiguous dates like '01-02-2026' that could be either DD-MM or MM-DD,
we default to DD-MM-YYYY (Indian convention) because the user is in India.
"""
from datetime import date, datetime


# All accepted input formats, tried in order. DD-first formats come first
# because user is in India.
_INPUT_FORMATS = [
    "%Y-%m-%d",     # 2026-04-29 (ISO, used internally and by HTML date inputs)
    "%d-%m-%Y",     # 29-04-2026
    "%d/%m/%Y",     # 29/04/2026
    "%d.%m.%Y",     # 29.04.2026
    "%d %m %Y",     # 29 04 2026
    "%d-%b-%Y",     # 29-Apr-2026
    "%d-%B-%Y",     # 29-April-2026
    "%d %b %Y",     # 29 Apr 2026
    "%d %B %Y",     # 29 April 2026
    "%Y/%m/%d",     # 2026/04/29
    "%Y.%m.%d",     # 2026.04.29
]


def parse_flexible_date(s):
    """Try multiple formats. Returns date object or None."""
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None

    # If already a date object, return it
    if isinstance(s, date) and not isinstance(s, datetime):
        return s

    # Strip any extra whitespace from the middle
    s_normalized = " ".join(s.split())

    for fmt in _INPUT_FORMATS:
        try:
            return datetime.strptime(s_normalized, fmt).date()
        except ValueError:
            continue
    return None


def format_display(d):
    """Format a date object/string as 'DD MM YYYY' for screen display."""
    if d is None:
        return ""
    if isinstance(d, str):
        d = parse_flexible_date(d)
        if d is None:
            return ""
    return d.strftime("%d %m %Y")


def format_iso(d):
    """Format as YYYY-MM-DD (used by HTML date inputs)."""
    if d is None:
        return ""
    if isinstance(d, str):
        d = parse_flexible_date(d)
        if d is None:
            return ""
    return d.strftime("%Y-%m-%d")
