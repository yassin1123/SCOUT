"""UK politics via RSS — hard-filtered (spec 6.6).

The user does not want Westminster noise. This source only supplies
headlines + summaries; the keyword gate in prefilter.py throws away
anything that doesn't plausibly touch tech, startups, funding, defence,
talent visas or AI/data regulation, the ranker makes the final call, and
the brief caps politics at 1-2 items. Same headlines-only discipline as
the FT: title + summary + link, never a full body.
"""

from __future__ import annotations

import datetime as dt

from models import Item
from sources import rss


def fetch(since: dt.datetime, cfg: dict) -> list[Item]:
    return rss.fetch_many(cfg.get("feeds") or [], "uk_politics", since)
