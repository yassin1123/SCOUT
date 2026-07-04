"""Shared RSS/Atom plumbing for the feed-based sources.

Per-feed failures are logged and skipped; the calling source only fails
outright (and lands in source_health + the brief footer) when every one
of its feeds failed. Titles and summaries are stripped to plain text —
Scout never carries article bodies.
"""

from __future__ import annotations

import datetime as dt
import logging

import feedparser
import requests

from models import Item
from util import clean_text, now_utc, struct_to_dt, to_utc

USER_AGENT = "scout-personal-brief/1.0 (personal RSS reader)"
logger = logging.getLogger("scout")


def fetch_feed_entries(url: str) -> list:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"unparseable feed ({feed.get('bozo_exception')})")
    return feed.entries


def entries_to_items(entries: list, source: str, since: dt.datetime) -> list[Item]:
    cutoff = to_utc(since)
    items: list[Item] = []
    for entry in entries:
        title = clean_text(entry.get("title", ""))
        link = entry.get("link", "")
        if not title or not link:
            continue
        published = struct_to_dt(
            entry.get("published_parsed") or entry.get("updated_parsed")
        ) or now_utc()
        if published < cutoff:
            continue
        items.append(
            Item(
                source=source,
                external_id=entry.get("id") or link,
                title=title,
                summary=clean_text(entry.get("summary", "") or entry.get("description", "")),
                url=link,
                published=published,
                raw_tags=[t.get("term", "") for t in entry.get("tags", []) if t.get("term")],
            )
        )
    return items


def fetch_many(urls: list[str], source: str, since: dt.datetime) -> list[Item]:
    """Fetch several feeds for one source; raise only if all of them fail."""
    items: list[Item] = []
    errors: list[str] = []
    for url in urls:
        try:
            items.extend(entries_to_items(fetch_feed_entries(url), source, since))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {type(exc).__name__}")
            logger.warning("feed failed for %s: %s (%s)", source, url, exc)
    if errors and not items and urls:
        raise RuntimeError(f"all {len(urls)} feeds failed: " + "; ".join(errors))
    return items
