"""Deadline parsing and the reminder engine (spec 6.5).

Parsing is best-effort by design: it only trusts a date that sits near a
deadline-ish trigger word ("deadline", "closes", "apply by", ...), so a
random date in a summary doesn't become a phantom deadline. Reminders
fire at the configured days-out marks (plus "closes today"), surface at
the top of the morning brief regardless of item score, and are marked
sent only after the email actually goes out.
"""

from __future__ import annotations

import datetime as dt
import re

from store import Store

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
_TRIGGER = (
    r"(?:deadline|closes?|closing|apply by|register by|registration (?:closes?|ends?)|"
    r"applications? (?:close|due)|submissions? (?:close|due|end)|due)"
)
# date shapes searched within a short window after a trigger word
_DAY_MONTH = re.compile(
    rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MONTH}\.?,?\s*(\d{{4}})?", re.IGNORECASE
)
_MONTH_DAY = re.compile(
    rf"{_MONTH}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s*(\d{{4}})?", re.IGNORECASE
)
_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_TRIGGER_RE = re.compile(_TRIGGER, re.IGNORECASE)
_WINDOW = 60  # chars after the trigger word to look for a date


def _resolve(day: int, month: int, year: int | None, today: dt.date) -> dt.date | None:
    try:
        if year is not None:
            return dt.date(year, month, day)
        candidate = dt.date(today.year, month, day)
        if candidate < today:  # "closes 5 Jan" said in December means next year
            candidate = dt.date(today.year + 1, month, day)
        return candidate
    except ValueError:
        return None


def parse_deadline(text: str, today: dt.date) -> dt.date | None:
    """Extract a deadline date from free text, or None."""
    if not text:
        return None
    for trigger in _TRIGGER_RE.finditer(text):
        window = text[trigger.end() : trigger.end() + _WINDOW]
        m = _ISO.search(window)
        if m:
            got = _resolve(int(m.group(3)), int(m.group(2)), int(m.group(1)), today)
            if got:
                return got
        m = _DAY_MONTH.search(window)
        if m:
            got = _resolve(
                int(m.group(1)), MONTHS[m.group(2).lower()[:3]],
                int(m.group(3)) if m.group(3) else None, today,
            )
            if got:
                return got
        m = _MONTH_DAY.search(window)
        if m:
            got = _resolve(
                int(m.group(2)), MONTHS[m.group(1).lower()[:3]],
                int(m.group(3)) if m.group(3) else None, today,
            )
            if got:
                return got
    return None


def collect_reminders(store: Store, cfg: dict, today: dt.date) -> list[dict]:
    """Reminders due today. Doesn't mark anything sent — call mark_sent()
    only after the email actually went out."""
    store.drop_expired_deadlines(today)
    windows = {int(d) for d in cfg.get("deadline_reminder_days", [14, 7, 3, 1])} | {0}
    reminders: list[dict] = []
    for row in store.unexpired_deadlines(today):
        deadline = dt.date.fromisoformat(row["deadline_date"])
        days_left = (deadline - today).days
        if days_left not in windows:
            continue
        if row["last_reminded_at"] == today.isoformat():
            continue  # never nag twice in one day
        if days_left == 0:
            line = "closes TODAY"
        else:
            line = f"{days_left} day{'s' if days_left != 1 else ''} left (closes {deadline.day} {deadline:%b})"
        reminders.append(
            {
                "external_id": row["external_id"],
                "title": row["title"],
                "url": row["url"],
                "line": line,
                "days": days_left,
            }
        )
    reminders.sort(key=lambda r: r["days"])
    return reminders


def mark_sent(store: Store, reminders: list[dict], today: dt.date) -> None:
    for r in reminders:
        store.mark_reminded(r["external_id"], today)
