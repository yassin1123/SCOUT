"""The Item schema — the one shape every source produces and every stage consumes."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

# The fixed set of route tags the ranker may assign (spec 7.2).
ROUTE_TAGS = ["Founder", "FDE", "Startup", "Markets", "Politics", "Opportunity", "General"]

# Display order in briefs: actionable first, background last (spec 8.1).
ROUTE_ORDER = ["Opportunity", "Founder", "FDE", "Startup", "Markets", "Politics", "General"]


@dataclass
class Item:
    source: str          # "arxiv" | "ft" | "ai_news" | "uk_politics" | "opportunity"
    external_id: str     # stable unique ID for dedupe (arXiv ID, RSS guid, URL)
    title: str
    summary: str         # abstract / standfirst / description — TEXT ONLY, no full body
    url: str
    published: dt.datetime
    raw_tags: list[str] = field(default_factory=list)  # source-native categories
    deadline: dt.date | None = None  # parseable opportunity deadline, if any
    # filled in later by the ranker:
    score: int = 0             # 0-100 relevance to the user
    route_tag: str = ""        # one of ROUTE_TAGS
    why: str = ""              # one-line "why this matters to you"
