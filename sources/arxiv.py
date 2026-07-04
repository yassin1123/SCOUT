"""arXiv fetcher — the core source (spec 6.2).

Pulls recent submissions across the configured categories via the public
arXiv API (Atom), dedupes by arXiv ID, and returns Items. The keyword
pre-filter and the daily cap are applied later, in prefilter.py, so the
"filtered N items" count in the brief footer stays accurate.
"""

from __future__ import annotations

import datetime as dt
import re

import feedparser
import requests

from models import Item
from util import UTC, clean_text, struct_to_dt, to_utc

API_URL = "https://export.arxiv.org/api/query"
USER_AGENT = "scout-personal-brief/1.0 (personal RSS reader)"

# arXiv announces items up to a few days after submission; look back a bit
# further than the watermark so late announcements aren't missed. The
# seen-items store guarantees nothing is ever shown twice.
ANNOUNCE_SLACK = dt.timedelta(days=3)


def _arxiv_id(entry_id: str) -> str:
    """http://arxiv.org/abs/2501.01234v2 -> 2501.01234"""
    tail = entry_id.rsplit("/abs/", 1)[-1]
    return re.sub(r"v\d+$", "", tail)


def fetch(since: dt.datetime, cfg: dict) -> list[Item]:
    categories = cfg.get("categories") or ["cs.AI", "cs.LG"]
    max_results = int(cfg.get("max_results", 150))
    query = " OR ".join(f"cat:{c}" for c in categories)

    resp = requests.get(
        API_URL,
        params={
            "search_query": query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    feed = feedparser.parse(resp.text)

    cutoff = to_utc(since) - ANNOUNCE_SLACK
    items: list[Item] = []
    for entry in feed.entries:
        published = struct_to_dt(entry.get("published_parsed")) or dt.datetime.now(UTC)
        if published < cutoff:
            continue
        items.append(
            Item(
                source="arxiv",
                external_id=f"arxiv:{_arxiv_id(entry.get('id', entry.get('link', '')))}",
                title=clean_text(entry.get("title", "")),
                summary=clean_text(entry.get("summary", "")),
                url=entry.get("link", ""),
                published=published,
                raw_tags=[t.get("term", "") for t in entry.get("tags", [])],
            )
        )
    return items
