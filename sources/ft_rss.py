"""FT via its open RSS feeds — headlines + standfirsts ONLY (spec 6.3).

Deliberate and non-negotiable: Scout never fetches FT article bodies and
never logs into anything. The subscription is the user's; Scout's job is
triage. The brief links the headline and the user opens it in their own
logged-in FT session. rss.py already carries only title + summary + link,
so the paywall discipline is structural, not a convention.
"""

from __future__ import annotations

import datetime as dt

from models import Item
from sources import rss


def fetch(since: dt.datetime, cfg: dict) -> list[Item]:
    return rss.fetch_many(cfg.get("feeds") or [], "ft", since)
