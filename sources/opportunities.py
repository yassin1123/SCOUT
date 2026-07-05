"""Hackathons + jobs, with deadline extraction (spec 6.5).

The fuzziest source — best-effort by design and honest about it (see
README). Three legs:

  * hackathon listing feeds (RSS), extendable in config;
  * public Greenhouse job boards, title-filtered by configurable keywords;
  * a manual list in config for anything else worth tracking, so its
    deadline gets recorded and reminded on.

No aggressive scraping, nothing behind a login, no ToS games. Items with
a parseable deadline carry it so the reminder engine can track it.
"""

from __future__ import annotations

import datetime as dt
import logging
import re

import requests

from deadlines import parse_deadline
from models import Item
from sources import rss
from util import keyword_match, now_utc, to_utc

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
logger = logging.getLogger("scout")


def _greenhouse_jobs(board: str, cfg: dict) -> list[Item]:
    keywords = cfg.get("job_keywords") or []
    resp = requests.get(
        GREENHOUSE_URL.format(board=board),
        headers={"User-Agent": rss.USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    jobs = resp.json().get("jobs") or []
    items: list[Item] = []
    for job in jobs:
        title = str(job.get("title", "")).strip()
        if not title or (keywords and not keyword_match(title, keywords)):
            continue
        location = str(((job.get("location") or {}).get("name")) or "").strip()
        try:
            published = to_utc(dt.datetime.fromisoformat(job["updated_at"]))
        except (KeyError, TypeError, ValueError):
            published = now_utc()
        items.append(
            Item(
                source="opportunity",
                external_id=f"gh:{board}:{job.get('id')}",
                title=f"{title} — {board.capitalize()}",
                summary=f"Live role on the {board.capitalize()} careers board."
                + (f" Location: {location}." if location else ""),
                url=str(job.get("absolute_url", "")),
                published=published,
                raw_tags=["job", board],
            )
        )
    return items


def _manual_items(entries: list) -> list[Item]:
    items: list[Item] = []
    for entry in entries or []:
        title = str(entry.get("title", "")).strip()
        if not title:
            continue
        deadline = entry.get("deadline")
        if isinstance(deadline, str):
            try:
                deadline = dt.date.fromisoformat(deadline)
            except ValueError:
                logger.warning("manual opportunity %r has unparseable deadline %r", title, deadline)
                deadline = None
        elif isinstance(deadline, dt.datetime):
            deadline = deadline.date()
        elif not isinstance(deadline, dt.date):
            deadline = None
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        items.append(
            Item(
                source="opportunity",
                external_id=f"manual:{slug}",
                title=title,
                summary=str(entry.get("notes", "")).strip(),
                url=str(entry.get("url", "")).strip(),
                published=now_utc(),
                raw_tags=["manual"],
                deadline=deadline,
            )
        )
    return items


def fetch(since: dt.datetime, cfg: dict) -> list[Item]:
    items: list[Item] = []
    failures: list[str] = []

    feeds = cfg.get("feeds") or []
    if feeds:
        try:
            items.extend(rss.fetch_many(feeds, "opportunity", since))
        except Exception as exc:  # noqa: BLE001
            failures.append(f"hackathon feeds ({type(exc).__name__})")
            logger.warning("hackathon feeds failed: %s", exc)

    for board in cfg.get("greenhouse_boards") or []:
        try:
            items.extend(_greenhouse_jobs(board, cfg))
        except Exception as exc:  # noqa: BLE001
            failures.append(f"greenhouse:{board} ({type(exc).__name__})")
            logger.warning("greenhouse board %s failed: %s", board, exc)

    items.extend(_manual_items(cfg.get("manual") or []))

    if failures and not items:
        raise RuntimeError("all opportunity legs failed: " + "; ".join(failures))

    # Best-effort deadline extraction for anything that didn't carry one.
    today = now_utc().date()
    for item in items:
        if item.deadline is None:
            item.deadline = parse_deadline(f"{item.title}. {item.summary}", today)
    return items
