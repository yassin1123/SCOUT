"""AI-industry news via RSS from primary sources (spec 6.4).

Feed list lives in config.yaml — primary sources (lab blogs) preferred
over aggregators. Anthropic-related items get their ranking boost inside
the profile-driven prompt, not here.
"""

from __future__ import annotations

import datetime as dt

from models import Item
from sources import rss


def fetch(since: dt.datetime, cfg: dict) -> list[Item]:
    return rss.fetch_many(cfg.get("feeds") or [], "ai_news", since)
