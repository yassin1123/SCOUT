"""Builds scout_context.md — the Claude-ready mentor bundle (spec 11.4).

One self-contained, paste-sized Markdown document: the full profile as
prose, the state of the routes, the last N days of briefs, standout
items, and open deadlines — topped with a framing header telling the
receiving Claude what role to play. Paste it into any Claude chat and
you're talking to a mentor that already knows everything.

Privacy: only the user's own profile and the public items Scout has
surfaced. No secrets, no Accenture data — there is none anywhere in
Scout to leak.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections import OrderedDict

from config import ROOT
from models import ROUTE_ORDER
from rank import profile_to_markdown
from store import Store
from util import local_now, now_utc, to_local

OUTPUT_PATH = ROOT / "scout_context.md"

FRAMING = (
    "> You are acting as this person's career mentor. Below is their full "
    "current context, exported from their personal intelligence tool "
    "(Scout). Reason from it. Be blunt and direct — they prefer no fluff. "
    "Their north star is founding; help them navigate every route toward it."
)


def _route_state_lines(store: Store, rows: list, window_days: int, tz: str) -> list[str]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["route_tag"]] = counts.get(row["route_tag"], 0) + 1
    lines = []
    now = now_utc()
    for tag in ROUTE_ORDER:
        n = counts.get(tag, 0)
        if n:
            lines.append(f"- **{tag}**: {n} item{'s' if n != 1 else ''} in the last {window_days} days.")
            continue
        last = store.last_shown_for_route(tag)
        if last is None:
            lines.append(f"- **{tag}**: nothing surfaced yet.")
        else:
            days = (now - last).days
            lines.append(f"- **{tag}**: quiet — nothing for {days} day{'s' if days != 1 else ''}.")
    return lines


def _briefs_by_day(rows: list, tz: str) -> list[str]:
    by_day: "OrderedDict[str, list]" = OrderedDict()
    for row in rows:  # already newest first
        sent_local = to_local(dt.datetime.fromisoformat(row["sent_at"]), tz)
        key = f"{sent_local:%a} {sent_local.day} {sent_local:%b}"
        by_day.setdefault(key, []).append(row)
    lines: list[str] = []
    for day, day_rows in by_day.items():
        lines.append(f"### {day}")
        for r in day_rows:
            why = f" — {r['why']}" if r["why"] else ""
            lines.append(f"- [{r['route_tag']} · {r['score']}] **{r['title']}**{why} <{r['url']}>")
        lines.append("")
    return lines


def _standouts(rows: list, limit: int = 5) -> list[str]:
    seen_titles: set[str] = set()
    top = []
    for r in sorted(rows, key=lambda r: r["score"], reverse=True):
        if r["title"] in seen_titles:
            continue
        seen_titles.add(r["title"])
        top.append(f"- [{r['score']}] **{r['title']}** ({r['route_tag']}) <{r['url']}>")
        if len(top) >= limit:
            break
    return top


def _deadline_lines(store: Store, today: dt.date) -> list[str]:
    lines = []
    for row in store.unexpired_deadlines(today):
        deadline = dt.date.fromisoformat(row["deadline_date"])
        days = (deadline - today).days
        when = "TODAY" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
        url = f" <{row['url']}>" if row["url"] else ""
        lines.append(f"- **{row['title']}** — closes {deadline.day} {deadline:%b} ({when}).{url}")
    return lines


def build_context(cfg: dict, profile: dict, store: Store) -> str:
    tz = cfg.get("timezone", "Europe/London")
    window_days = int((cfg.get("export") or {}).get("window_days", 7))
    since = now_utc() - dt.timedelta(days=window_days)
    rows = store.items_shown_since(since)
    today = local_now(tz).date()
    stamp = local_now(tz)

    parts: list[str] = [
        f"# Scout context bundle — {stamp:%a} {stamp.day} {stamp:%b} {stamp:%Y}",
        "",
        FRAMING,
        "",
        "## 1. Who they are (full profile)",
        "",
        profile_to_markdown(profile),
        "",
        f"## 2. State of the routes (last {window_days} days)",
        "",
        *_route_state_lines(store, rows, window_days, tz),
        "",
        f"## 3. What Scout showed them — last {window_days} days",
        "",
    ]
    parts.extend(_briefs_by_day(rows, tz) or ["(no briefs in the window yet)", ""])
    parts += ["## 4. Standout items in the window", ""]
    parts.extend(_standouts(rows) or ["(none yet)"])
    parts += ["", "## 5. Open threads & deadlines", ""]
    parts.extend(_deadline_lines(store, today) or ["(no tracked deadlines)"])
    parts.append("")
    return "\n".join(parts)


def run_export(cfg: dict, profile: dict, store: Store, logger: logging.Logger) -> int:
    content = build_context(cfg, profile, store)
    OUTPUT_PATH.write_text(content, encoding="utf-8")
    logger.info("wrote %s (%d chars)", OUTPUT_PATH, len(content))
    print(f"Context bundle written to {OUTPUT_PATH}")
    return 0
