"""SQLite state: seen-items dedupe and the score cache.

One file (data/scout.db), created on first run. No database server.
All datetimes are stored as UTC ISO-8601 strings.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

from models import Item
from util import from_iso, iso, now_utc

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_items (
    external_id   TEXT PRIMARY KEY,
    source        TEXT NOT NULL,
    title         TEXT NOT NULL,
    url           TEXT NOT NULL,
    published     TEXT NOT NULL,
    first_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scores (
    external_id TEXT PRIMARY KEY,
    score       INTEGER NOT NULL,
    route_tag   TEXT NOT NULL,
    why         TEXT NOT NULL,
    scored_at   TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------------ seen
    def filter_unseen(self, items: list[Item]) -> list[Item]:
        """Drop anything already recorded, and in-batch duplicates."""
        out: list[Item] = []
        batch_ids: set[str] = set()
        for item in items:
            if item.external_id in batch_ids:
                continue
            row = self.db.execute(
                "SELECT 1 FROM seen_items WHERE external_id = ?", (item.external_id,)
            ).fetchone()
            if row is None:
                batch_ids.add(item.external_id)
                out.append(item)
        return out

    def mark_seen(self, items: list[Item]) -> None:
        now = iso(now_utc())
        self.db.executemany(
            "INSERT OR IGNORE INTO seen_items"
            " (external_id, source, title, url, published, first_seen_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [(i.external_id, i.source, i.title, i.url, iso(i.published), now) for i in items],
        )
        self.db.commit()

    # ---------------------------------------------------------------- scores
    def get_score(self, external_id: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT score, route_tag, why FROM scores WHERE external_id = ?",
            (external_id,),
        ).fetchone()

    def save_score(self, external_id: str, score: int, route_tag: str, why: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO scores (external_id, score, route_tag, why, scored_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (external_id, score, route_tag, why, iso(now_utc())),
        )
        self.db.commit()
