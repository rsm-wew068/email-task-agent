"""Due-date resolution (Validate stage input, §7).

Rule-based and deterministic — the same rules the E1 labeling conventions use
(§9.2), so gold labels and runtime behavior agree:

  anchored to the email's date:
    "friday"                 -> the coming Friday (anchor excluded)
    "next friday"            -> the coming Friday + 7
    "end of the week" / EOW  -> Friday of the email's week
    "end of the month" / EOM -> last day of the email's month
    "today"/"end of day"/EOD -> the email's date
    "tomorrow"               -> email date + 1
    "next week"              -> email date + 7
    "in 3 days"              -> email date + 3
    "by the 20th"            -> the 20th of the email's month (next month if past)
    "november 15" / "15 nov" -> that date this year (next year if past)
  ISO "2026-11-06" passes through.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_MONTH_DAY_RE = re.compile(r"^([a-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?$", re.IGNORECASE)
_DAY_MONTH_RE = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?\s+of\s+([a-z]+)$", re.IGNORECASE)
_DAY_NUM_RE = re.compile(r"^the\s+(\d{1,2})(?:st|nd|rd|th)?$", re.IGNORECASE)
_IN_N_DAYS_RE = re.compile(r"^in\s+(\d{1,2})\s+days?$", re.IGNORECASE)
_WEEKDAY_RE = re.compile(r"^(?:this\s+|by\s+|coming\s+)?([a-z]+day)$", re.IGNORECASE)
_NEXT_WEEKDAY_RE = re.compile(r"^next\s+([a-z]+day)$", re.IGNORECASE)


def _coming_weekday(anchor: date, weekday: int, *, skip_ahead: int = 0) -> date:
    delta = (weekday - anchor.weekday()) % 7
    if delta == 0:
        delta = 7
    return anchor + timedelta(days=delta + skip_ahead)


def _month_day(anchor: date, month: int, day: int) -> date | None:
    try:
        candidate = date(anchor.year, month, day)
    except ValueError:
        return None
    if candidate < anchor:
        try:
            candidate = date(anchor.year + 1, month, day)
        except ValueError:
            return None
    return candidate


def resolve_due_date(raw: str | None, anchor: date) -> date | None:
    """Resolve a due-date phrase against the email date; None if unparseable.

    An ISO date or a resolvable relative phrase returns a date; anything else
    (including None) returns None — the Validate stage flags needs_review for
    non-None unparseable phrases, and treats None as "no stated date".
    """
    if not raw:
        return None
    text = raw.strip().casefold()

    if iso := _ISO_RE.match(text):
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None

    if (m := _IN_N_DAYS_RE.match(text)) :
        return anchor + timedelta(days=int(m.group(1)))

    if text in {"today", "end of day", "eod", "end of today"}:
        return anchor
    if text in {"tomorrow", "end of tomorrow"}:
        return anchor + timedelta(days=1)
    if text in {"next week", "a week from now"}:
        return anchor + timedelta(days=7)
    if text in {"end of the week", "end of week", "eow", "by the end of the week", "by end of week"}:
        if anchor.weekday() < 4:
            return _coming_weekday(anchor, 4)
        if anchor.weekday() == 4:  # emailed on Friday: the end of this week is today
            return anchor
        return anchor + timedelta(days=7 - (anchor.weekday() - 4))
    if text in {"end of the month", "end of month", "eom", "by the end of the month"}:
        return date(anchor.year, anchor.month, calendar.monthrange(anchor.year, anchor.month)[1])

    if m := _MONTH_DAY_RE.match(text):
        month = _MONTHS.get(m.group(1).casefold())
        return _month_day(anchor, month, int(m.group(2))) if month else None

    if m := _DAY_MONTH_RE.match(text):
        month = _MONTHS.get(m.group(2).casefold())
        return _month_day(anchor, month, int(m.group(1))) if month else None

    if m := _DAY_NUM_RE.match(text):
        day = int(m.group(1))
        try:
            candidate = date(anchor.year, anchor.month, day)
        except ValueError:
            return None
        if candidate <= anchor:  # rolled past: same day next month
            if anchor.month < 12:
                year, month = anchor.year, anchor.month + 1
            else:
                year, month = anchor.year + 1, 1
            if day > calendar.monthrange(year, month)[1]:
                return None
            candidate = date(year, month, day)
        return candidate

    if m := _NEXT_WEEKDAY_RE.match(text):
        weekday = _WEEKDAYS.get(m.group(1).casefold())
        return _coming_weekday(anchor, weekday, skip_ahead=7) if weekday is not None else None

    if m := _WEEKDAY_RE.match(text):
        weekday = _WEEKDAYS.get(m.group(1).casefold())
        return _coming_weekday(anchor, weekday) if weekday is not None else None

    return None
