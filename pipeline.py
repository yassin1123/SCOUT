"""The per-run sequence (spec Section 2): fetch, dedupe, pre-filter, rank,
deadline check, assemble, deliver, record. One broken source never kills
the run; every failure is caught, logged and surfaced in the brief footer.
"""

from __future__ import annotations

import datetime as dt
import logging

import prefilter
from config import source_cfg, source_enabled
from models import Item
from sources import arxiv
from store import Store
from util import local_now, now_utc, to_utc

# Grows as sources land (spec build order, Section 12).
SOURCE_FETCHERS = {
    "arxiv": arxiv.fetch,
}


def _local_midnight_utc(cfg: dict) -> dt.datetime:
    tz = cfg.get("timezone", "Europe/London")
    midnight = local_now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return to_utc(midnight)


def fetch_all(
    cfg: dict, store: Store, logger: logging.Logger, since: dt.datetime
) -> list[Item]:
    """Pull every enabled source. Failures are recorded, not fatal."""
    items: list[Item] = []
    for name, fetcher in SOURCE_FETCHERS.items():
        if not source_enabled(cfg, name):
            continue
        try:
            fetched = fetcher(since, source_cfg(cfg, name))
            items.extend(fetched)
            store.record_source_ok(name)
            logger.info("source %-12s fetched %d items", name, len(fetched))
        except Exception as exc:  # noqa: BLE001 — a broken source must not kill the run
            store.record_source_error(name, f"{type(exc).__name__}: {exc}")
            logger.warning("source %-12s FAILED: %s", name, exc)
    return items


def run_brief(
    mode: str,
    cfg: dict,
    profile: dict,
    secrets: dict,
    store: Store,
    logger: logging.Logger,
    force: bool = False,
    dry_run: bool = False,
) -> int:
    # Idempotent runs (spec 13): at most one useful brief per mode per day.
    if not force and store.ran_ok_since(mode, _local_midnight_utc(cfg)):
        logger.info("%s already ran today — skipping (use --force to resend)", mode)
        return 0

    run_id = store.start_run(mode)
    lookback = dt.timedelta(hours=int(cfg.get("first_run_lookback_hours", 24)))
    since = store.last_fetch_time() or (now_utc() - lookback)
    logger.info("fetching everything since %s", since.isoformat(timespec="seconds"))

    fetched = fetch_all(cfg, store, logger, since)
    new_items = store.filter_unseen(fetched)
    kept, prefiltered_out = prefilter.apply(new_items, cfg)
    logger.info(
        "fetched %d, new %d, pre-filter kept %d (dropped %d)",
        len(fetched), len(new_items), len(kept), prefiltered_out,
    )

    # Ranking, assembly and delivery are wired in the next build steps.
    for item in sorted(kept, key=lambda i: i.published, reverse=True):
        print(f"[{item.source}] {item.title}\n    {item.url}")

    store.finish_run(
        run_id,
        status="dry-run",  # becomes 'ok' once delivery lands — watermark untouched until then
        items_fetched=len(new_items),
        items_ranked=len(kept),
        items_sent=0,
    )
    return 0
