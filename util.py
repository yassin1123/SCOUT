"""Small shared helpers: time handling and keyword matching."""

from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

UTC = dt.timezone.utc


def now_utc() -> dt.datetime:
    return dt.datetime.now(UTC)


def to_utc(d: dt.datetime) -> dt.datetime:
    """Normalise any datetime (naive assumed UTC) to an aware UTC datetime."""
    if d.tzinfo is None:
        return d.replace(tzinfo=UTC)
    return d.astimezone(UTC)


def iso(d: dt.datetime) -> str:
    return to_utc(d).isoformat(timespec="seconds")


def from_iso(s: str) -> dt.datetime:
    return to_utc(dt.datetime.fromisoformat(s))


def local_now(tz_name: str) -> dt.datetime:
    return dt.datetime.now(ZoneInfo(tz_name))


def to_local(d: dt.datetime, tz_name: str) -> dt.datetime:
    return to_utc(d).astimezone(ZoneInfo(tz_name))


def struct_to_dt(t) -> dt.datetime | None:
    """feedparser's *_parsed struct_time (UTC) -> aware datetime, or None."""
    if not t:
        return None
    return dt.datetime(*t[:6], tzinfo=UTC)


def keyword_match(text: str, keywords: list[str]) -> bool:
    """True if any keyword appears in text as a whole token.

    Word-boundary matching so short keywords like "RL" don't fire inside
    "world". Multi-word keywords ("tool use", "on-device") match literally,
    case-insensitive.
    """
    if not text:
        return False
    for kw in keywords:
        pattern = r"(?<![A-Za-z0-9])" + re.escape(str(kw)) + r"(?![A-Za-z0-9])"
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def clean_text(s: str | None) -> str:
    """Strip HTML tags and collapse whitespace — summaries are text only."""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"&nbsp;?", " ", s)
    s = re.sub(r"&amp;", "&", s)
    s = re.sub(r"&#39;|&apos;", "'", s)
    s = re.sub(r"&quot;", '"', s)
    s = re.sub(r"&lt;", "<", s)
    s = re.sub(r"&gt;", ">", s)
    return re.sub(r"\s+", " ", s).strip()
