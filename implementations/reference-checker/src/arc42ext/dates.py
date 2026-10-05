"""Dates and durations as defined by triggers rule T13."""

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DURATION = re.compile(r"^P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?$")


@dataclass(frozen=True)
class Duration:
    years: int = 0
    months: int = 0
    weeks: int = 0
    days: int = 0
    text: str = ""

    def __str__(self):
        return self.text


def parse_date(text: str) -> Optional[date]:
    text = text.strip()
    if not _DATE.match(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def parse_duration(text: str) -> Optional[Duration]:
    text = text.strip()
    m = _DURATION.match(text)
    if not m or text == "P":
        return None
    y, mo, w, d = (int(g) if g else 0 for g in m.groups())
    return Duration(y, mo, w, d, text)


def _add_months(d: date, months: int) -> date:
    total = d.year * 12 + (d.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def add(d: date, duration: Duration) -> date:
    """Add years, then months (clamping to month end), then weeks and days."""
    d = _add_months(d, duration.years * 12)
    d = _add_months(d, duration.months)
    return d + timedelta(weeks=duration.weeks, days=duration.days)
