"""Assembles the briefs — the thing the user actually experiences (spec 8).

Tone rules apply everywhere: blunt, direct, no fluff, no corporate cheer,
no emoji, no hype. HTML is simple, inline-styled and mobile-readable.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter

from jinja2 import Environment, FileSystemLoader

from config import ROOT, source_cfg, source_enabled
from models import ROUTE_ORDER, Item
from util import to_local

SOURCE_LABELS = {
    "arxiv": "arXiv",
    "ft": "FT",
    "ai_news": "AI news",
    "uk_politics": "UK politics",
    "opportunity": "Opportunity",
    "opportunities": "Opportunities",  # fetcher name, used in failure notes
}

_loader = FileSystemLoader(str(ROOT / "templates"))
_html_env = Environment(loader=_loader, autoescape=True, trim_blocks=True, lstrip_blocks=True)
_text_env = Environment(loader=_loader, autoescape=False, trim_blocks=True, lstrip_blocks=True)


def _date_str(cfg: dict) -> str:
    d = to_local(dt.datetime.now(dt.timezone.utc), cfg.get("timezone", "Europe/London"))
    return f"{d:%a} {d.day} {d:%b}"


def select_items(ranked: list[Item], cfg: dict, mode: str) -> list[Item]:
    """Top N by score, with the hard politics cap and the score floor."""
    max_items = int(cfg.get(f"max_items_{mode}", 6))
    min_score = int(cfg.get("min_score_to_show", 45))
    politics_cap = int(source_cfg(cfg, "uk_politics").get("max_items", 2))

    chosen: list[Item] = []
    politics_shown = 0
    for item in sorted(ranked, key=lambda i: i.score, reverse=True):
        if item.score < min_score:
            break  # sorted — nothing below clears the bar
        if item.route_tag == "Politics":
            if politics_shown >= politics_cap:
                continue
            politics_shown += 1
        chosen.append(item)
        if len(chosen) >= max_items:
            break
    return chosen


def group_items(chosen: list[Item], cfg: dict) -> list[tuple[str, list[dict]]]:
    groups: list[tuple[str, list[dict]]] = []
    for tag in ROUTE_ORDER:
        rows = [
            {
                "title": i.title,
                "url": i.url,
                "why": i.why,
                "score": i.score,
                "source_label": SOURCE_LABELS.get(i.source, i.source),
                "date": f"{to_local(i.published, cfg.get('timezone', 'Europe/London')):%d %b}",
            }
            for i in sorted(chosen, key=lambda x: x.score, reverse=True)
            if i.route_tag == tag
        ]
        if rows:
            groups.append((tag, rows))
    return groups


def day_read(chosen: list[Item], cfg: dict, mode: str) -> str:
    """The one-line read of the day at the top of the brief."""
    if not chosen:
        return (
            "Quiet since this morning."
            if mode == "evening"
            else "Quiet day — nothing cleared the bar."
        )
    counts = Counter(i.route_tag for i in chosen)
    parts = ", ".join(f"{counts[tag]} {tag}" for tag in ROUTE_ORDER if counts.get(tag))
    n = len(chosen)
    line = f"{n} thing{'s' if n != 1 else ''} worth your time: {parts}."
    if source_enabled(cfg, "arxiv") and not any(i.source == "arxiv" for i in chosen):
        line += " arXiv quiet."
    return line


def build_footer_lines(
    new_count: int, shown_count: int, failing: list[tuple[str, str]], rank_stats: dict | None
) -> list[str]:
    lines = []
    filtered = max(0, new_count - shown_count)
    lines.append(f"Filtered {filtered} item{'s' if filtered != 1 else ''} you didn't need to see.")
    for source, err in failing:
        label = SOURCE_LABELS.get(source, source)
        lines.append(f"Heads up: {label} failed to fetch this run ({err}).")
    if rank_stats and rank_stats.get("failed_items"):
        lines.append(
            f"Ranking degraded for {rank_stats['failed_items']} items (API trouble) — "
            "neutral scores used; they'll re-score next run."
        )
    return lines


def build_brief(
    mode: str,
    chosen: list[Item],
    cfg: dict,
    reminders: list[dict] | None = None,
    quiet_lines: list[str] | None = None,
    footer_lines: list[str] | None = None,
) -> dict:
    """Returns {subject, html, text} for a morning or evening brief."""
    reminders = reminders or []
    date_str = _date_str(cfg)
    n = len(chosen)

    if mode == "morning":
        mode_label = "AM"
        subject = (
            f"Scout AM — {date_str} — {n} thing{'s' if n != 1 else ''} worth your time"
            if n
            else f"Scout AM — {date_str} — quiet day"
        )
    else:
        mode_label = "PM"
        subject = (
            f"Scout PM — {date_str} — {n} new since this morning"
            if n
            else f"Scout PM — {date_str} — quiet since this morning"
        )

    context = {
        "mode_label": mode_label,
        "date_str": date_str,
        "day_read": day_read(chosen, cfg, mode),
        "reminders": reminders,
        "groups": group_items(chosen, cfg),
        "quiet_body": (
            "Nothing meaningful landed since this morning. Enjoy the evening."
            if (mode == "evening" and not chosen)
            else ""
        ),
        "quiet_lines": quiet_lines or [],
        "footer_lines": footer_lines or [],
    }
    return {
        "subject": subject,
        "html": _html_env.get_template("brief.html.j2").render(**context),
        "text": _text_env.get_template("brief.txt.j2").render(**context),
    }
