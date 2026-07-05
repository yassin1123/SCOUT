"""The Item schema — the one shape every source produces and every stage consumes."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

# Briefs group by plain content section, derived mechanically from the source —
# no model ever assigns a label to the reader's life.
SECTION_ORDER = ["Opportunities", "Papers", "News", "Politics"]
SOURCE_SECTION = {
    "arxiv": "Papers",
    "ai_news": "News",
    "ft": "News",
    "uk_politics": "Politics",
    "opportunity": "Opportunities",
}


def section_for(source: str) -> str:
    return SOURCE_SECTION.get(source, "News")


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
    # filled in later:
    section: str = ""          # one of SECTION_ORDER, set from the source
    score: int = 0             # 0-100 interest score from the ranker
    why: str = ""              # one neutral line: what it is, why it's notable
