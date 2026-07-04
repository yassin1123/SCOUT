"""The per-run sequence (spec Section 2): fetch, dedupe, pre-filter, rank,
deadline check, assemble, deliver, record. One broken source never kills
the run; every failure is caught, logged and surfaced in the brief footer.
"""

from __future__ import annotations

import datetime as dt
import logging

import brief
import deadlines
import mailer
import prefilter
import rank
from config import source_cfg, source_enabled
from models import Item
from sources import ai_news, arxiv, ft_rss, opportunities, uk_politics
from store import Store
from util import local_now, now_utc, to_utc

SOURCE_FETCHERS = {
    "arxiv": arxiv.fetch,
    "ai_news": ai_news.fetch,
    "uk_politics": uk_politics.fetch,
    "ft": ft_rss.fetch,
    "opportunities": opportunities.fetch,
}


def _local_midnight_utc(cfg: dict) -> dt.datetime:
    tz = cfg.get("timezone", "Europe/London")
    midnight = local_now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return to_utc(midnight)


def fetch_all(
    cfg: dict, store: Store, logger: logging.Logger, since: dt.datetime
) -> tuple[list[Item], list[tuple[str, str]]]:
    """Pull every enabled source. Failures are recorded and reported, not fatal."""
    items: list[Item] = []
    failures: list[tuple[str, str]] = []
    for name, fetcher in SOURCE_FETCHERS.items():
        if not source_enabled(cfg, name):
            continue
        try:
            fetched = fetcher(since, source_cfg(cfg, name))
            items.extend(fetched)
            store.record_source_ok(name)
            logger.info("source %-12s fetched %d items", name, len(fetched))
        except Exception as exc:  # noqa: BLE001 — a broken source must not kill the run
            error = f"{type(exc).__name__}: {exc}"
            store.record_source_error(name, error)
            failures.append((name, type(exc).__name__))
            logger.warning("source %-12s FAILED: %s", name, exc)
    return items, failures


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

    fetched, failures = fetch_all(cfg, store, logger, since)
    new_items = store.filter_unseen(fetched)
    kept, prefiltered_out = prefilter.apply(new_items, cfg)
    logger.info(
        "fetched %d, new %d, pre-filter kept %d (dropped %d)",
        len(fetched), len(new_items), len(kept), prefiltered_out,
    )

    # Deadline tracking (spec 6.5): every fetched item with a future deadline
    # is (re)recorded — including already-seen ones, so an edited manual
    # deadline propagates even though the item won't be shown again.
    today = local_now(cfg.get("timezone", "Europe/London")).date()
    for item in fetched:
        if item.deadline and item.deadline >= today:
            store.upsert_deadline(item.external_id, item.title, item.url, item.deadline)

    # Reminders are a morning thing — time-critical, always at the top.
    reminders = deadlines.collect_reminders(store, cfg, today) if mode == "morning" else []
    if reminders:
        logger.info("deadline reminders due: %d", len(reminders))

    stats = rank.rank_items(kept, profile, cfg, store, logger)
    cost_note = (
        f"api_calls={stats['api_calls']} cache_hits={stats['cache_hits']}"
        f" tokens_in={stats['input_tokens']} tokens_out={stats['output_tokens']}"
        f" est_cost=${stats['cost_usd']:.4f} failed={stats['failed_items']}"
    )
    logger.info("ranking: %s", cost_note)

    shown = brief.select_items(kept, cfg, mode)
    footer_lines = brief.build_footer_lines(len(new_items), len(shown), failures, stats)
    doc = brief.build_brief(mode, shown, cfg, reminders=reminders, footer_lines=footer_lines)

    # The evening email always carries a fresh context bundle (spec 8.2), so
    # a current mentor snapshot is always one inbox search away.
    attachments = []
    if mode == "evening":
        try:
            import export

            bundle = export.build_context(cfg, profile, store)
            export.OUTPUT_PATH.write_text(bundle, encoding="utf-8")
            attachments.append(("scout_context.md", bundle.encode("utf-8"), "text", "markdown"))
        except Exception:  # noqa: BLE001 — the brief still goes out without it
            logger.exception("could not build context bundle for the evening email")

    if dry_run:
        mailer.save_fallback(doc["html"], logger)
        logger.info("dry-run: would send %r with %d items", doc["subject"], len(shown))
        store.finish_run(
            run_id, "dry-run",
            items_fetched=len(new_items), items_ranked=len(kept),
            items_sent=len(shown), notes=cost_note,
        )
        return 0

    sent = mailer.send_brief(
        doc["subject"], doc["html"], doc["text"], secrets, cfg, logger,
        attachments=attachments,
    )
    if not sent:
        # Items stay un-seen so they come back next run — nothing is lost.
        store.finish_run(
            run_id, "error",
            items_fetched=len(new_items), items_ranked=len(kept),
            items_sent=0, notes=cost_note + "; send failed",
        )
        return 1

    store.mark_seen(new_items)  # everything fetched is now history, shown or not
    store.record_brief_items(run_id, shown)
    deadlines.mark_sent(store, reminders, today)  # only after a real send
    store.finish_run(
        run_id, "ok",
        items_fetched=len(new_items), items_ranked=len(kept),
        items_sent=len(shown), notes=cost_note,
    )
    logger.info("%s brief delivered: %d items shown", mode, len(shown))
    return 0
