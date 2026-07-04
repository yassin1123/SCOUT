"""Cheap keyword/heuristic cut before any API spend (spec 6.2 and 6.6).

Rules by source:
  * arxiv       — title/abstract must hit a ranking.prefilter_keywords term;
                  then capped to the daily_cap most recent.
  * uk_politics — must hit the politics keyword gate (no Westminster noise
                  ever reaches the ranker).
  * everything else — already curated feeds; passes through.

Returns (kept, dropped_count) so the brief footer can report exactly how
many items the user was spared.
"""

from __future__ import annotations

from config import source_cfg
from models import Item
from util import keyword_match


def apply(items: list[Item], cfg: dict) -> tuple[list[Item], int]:
    ranking_kws = (cfg.get("ranking") or {}).get("prefilter_keywords") or []
    politics_kws = source_cfg(cfg, "uk_politics").get("keywords") or []
    arxiv_cap = int(source_cfg(cfg, "arxiv").get("daily_cap", 40))

    arxiv_kept: list[Item] = []
    kept: list[Item] = []
    dropped = 0

    for item in items:
        text = f"{item.title} {item.summary}"
        if item.source == "arxiv":
            if keyword_match(text, ranking_kws):
                arxiv_kept.append(item)
            else:
                dropped += 1
        elif item.source == "uk_politics":
            if keyword_match(text, politics_kws):
                kept.append(item)
            else:
                dropped += 1
        else:
            kept.append(item)

    # Cap what reaches the ranker: most recent first (spec 6.2).
    arxiv_kept.sort(key=lambda i: i.published, reverse=True)
    if len(arxiv_kept) > arxiv_cap:
        dropped += len(arxiv_kept) - arxiv_cap
        arxiv_kept = arxiv_kept[:arxiv_cap]

    return arxiv_kept + kept, dropped
