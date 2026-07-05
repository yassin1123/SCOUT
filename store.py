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

CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    mode          TEXT NOT NULL,            -- morning | evening | weekly
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    items_fetched INTEGER DEFAULT 0,
    items_ranked  INTEGER DEFAULT 0,
    items_sent    INTEGER DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'running',  -- running | ok | error | dry-run | skipped
    notes         TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS source_health (
    source          TEXT PRIMARY KEY,
    last_success_at TEXT,
    last_error      TEXT
);

CREATE TABLE IF NOT EXISTS deadlines (
    external_id      TEXT PRIMARY KEY,
    title            TEXT NOT NULL,
    url              TEXT NOT NULL,
    deadline_date    TEXT NOT NULL,          -- YYYY-MM-DD
    last_reminded_at TEXT                     -- YYYY-MM-DD of the last reminder
);

-- What each brief actually showed. Powers quiet-route reporting, the weekly
-- digest and the context export ("the items shown, grouped by day").
CREATE TABLE IF NOT EXISTS brief_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL,
    external_id TEXT NOT NULL,
    route_tag   TEXT NOT NULL,
    score       INTEGER NOT NULL,
    position    INTEGER NOT NULL,
    sent_at     TEXT NOT NULL
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

    # ------------------------------------------------------------------ runs
    def start_run(self, mode: str) -> int:
        cur = self.db.execute(
            "INSERT INTO runs (mode, started_at, status) VALUES (?, ?, 'running')",
            (mode, iso(now_utc())),
        )
        self.db.commit()
        return int(cur.lastrowid)

    def finish_run(
        self,
        run_id: int,
        status: str,
        items_fetched: int = 0,
        items_ranked: int = 0,
        items_sent: int = 0,
        notes: str = "",
    ) -> None:
        self.db.execute(
            "UPDATE runs SET finished_at = ?, status = ?, items_fetched = ?,"
            " items_ranked = ?, items_sent = ?, notes = ? WHERE id = ?",
            (iso(now_utc()), status, items_fetched, items_ranked, items_sent, notes, run_id),
        )
        self.db.commit()

    def last_fetch_time(self) -> dt.datetime | None:
        """Watermark for fetchers: finish time of the most recent successful
        fetching run (morning or evening). Skipped runs self-heal because the
        watermark simply stays older (spec Sections 4 and 10)."""
        row = self.db.execute(
            "SELECT MAX(finished_at) AS t FROM runs"
            " WHERE mode IN ('morning', 'evening') AND status = 'ok'"
        ).fetchone()
        return from_iso(row["t"]) if row and row["t"] else None

    def ran_ok_since(self, mode: str, since: dt.datetime) -> bool:
        """Idempotency guard: has this mode already completed after `since`?"""
        row = self.db.execute(
            "SELECT 1 FROM runs WHERE mode = ? AND status = 'ok' AND started_at >= ? LIMIT 1",
            (mode, iso(since)),
        ).fetchone()
        return row is not None

    # -------------------------------------------------------- source health
    def record_source_ok(self, source: str) -> None:
        self.db.execute(
            "INSERT INTO source_health (source, last_success_at, last_error)"
            " VALUES (?, ?, NULL)"
            " ON CONFLICT(source) DO UPDATE SET last_success_at = excluded.last_success_at,"
            " last_error = NULL",
            (source, iso(now_utc())),
        )
        self.db.commit()

    def record_source_error(self, source: str, error: str) -> None:
        self.db.execute(
            "INSERT INTO source_health (source, last_error) VALUES (?, ?)"
            " ON CONFLICT(source) DO UPDATE SET last_error = excluded.last_error",
            (source, error[:300]),
        )
        self.db.commit()

    def failing_sources(self) -> list[tuple[str, str]]:
        rows = self.db.execute(
            "SELECT source, last_error FROM source_health WHERE last_error IS NOT NULL"
        ).fetchall()
        return [(r["source"], r["last_error"]) for r in rows]

    # -------------------------------------------------------------- deadlines
    def upsert_deadline(self, external_id: str, title: str, url: str, deadline: dt.date) -> None:
        self.db.execute(
            "INSERT INTO deadlines (external_id, title, url, deadline_date) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(external_id) DO UPDATE SET title = excluded.title,"
            " url = excluded.url, deadline_date = excluded.deadline_date",
            (external_id, title, url, deadline.isoformat()),
        )
        self.db.commit()

    def drop_expired_deadlines(self, today: dt.date) -> None:
        self.db.execute("DELETE FROM deadlines WHERE deadline_date < ?", (today.isoformat(),))
        self.db.commit()

    def unexpired_deadlines(self, today: dt.date) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM deadlines WHERE deadline_date >= ? ORDER BY deadline_date",
            (today.isoformat(),),
        ).fetchall()

    def mark_reminded(self, external_id: str, on: dt.date) -> None:
        self.db.execute(
            "UPDATE deadlines SET last_reminded_at = ? WHERE external_id = ?",
            (on.isoformat(), external_id),
        )
        self.db.commit()

    # ------------------------------------------------------------ brief items
    # NOTE: the route_tag column predates the topic-section refactor; it now
    # simply stores the item's section string. Kept for schema compatibility.
    def record_brief_items(self, run_id: int, items: list[Item]) -> None:
        now = iso(now_utc())
        self.db.executemany(
            "INSERT INTO brief_items (run_id, external_id, route_tag, score, position, sent_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [
                (run_id, item.external_id, item.section, item.score, pos, now)
                for pos, item in enumerate(items)
            ],
        )
        self.db.commit()

    def items_shown_since(self, since: dt.datetime) -> list[sqlite3.Row]:
        """Brief history joined with titles and why-lines, newest first."""
        return self.db.execute(
            "SELECT b.sent_at, b.route_tag, b.score, s.title, s.url, s.source,"
            "       COALESCE(sc.why, '') AS why"
            " FROM brief_items b"
            " JOIN seen_items s ON s.external_id = b.external_id"
            " LEFT JOIN scores sc ON sc.external_id = b.external_id"
            " WHERE b.sent_at >= ?"
            " ORDER BY b.sent_at DESC, b.score DESC",
            (iso(since),),
        ).fetchall()
