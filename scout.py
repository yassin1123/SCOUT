#!/usr/bin/env python3
"""Scout — a twice-daily AI/tech intelligence brief, filtered to one person's career.

Usage:
    python scout.py morning            # fuller sweep, main brief
    python scout.py evening            # lighter delta since the morning
    python scout.py weekly             # Sunday synthesis digest
    python scout.py export             # write scout_context.md (mentor bundle)

Flags:
    --dry-run   fetch and rank but send nothing, change no state
    --force     run even if this mode already completed today
"""

from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler

from config import ROOT, ConfigError, load_config, load_env, load_profile
from store import Store


def setup_logging() -> logging.Logger:
    logs_dir = ROOT / "logs"
    logs_dir.mkdir(exist_ok=True)
    logger = logging.getLogger("scout")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
        file_handler = RotatingFileHandler(
            logs_dir / "scout.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        logger.addHandler(file_handler)
        logger.addHandler(console)
    return logger


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scout — personal AI/tech intelligence brief")
    parser.add_argument("mode", choices=["morning", "evening", "weekly", "export"])
    parser.add_argument("--dry-run", action="store_true", help="no email, no state changes")
    parser.add_argument("--force", action="store_true", help="run even if already ran today")
    args = parser.parse_args(argv)

    logger = setup_logging()
    try:
        cfg = load_config()
        profile = load_profile()
        secrets = load_env()
    except ConfigError as exc:
        logger.error("config problem: %s", exc)
        return 2

    store = Store(ROOT / "data" / "scout.db")
    try:
        logger.info("scout %s starting%s", args.mode, " (dry-run)" if args.dry_run else "")
        if args.mode in ("morning", "evening"):
            import pipeline

            return pipeline.run_brief(
                args.mode, cfg, profile, secrets, store, logger,
                force=args.force, dry_run=args.dry_run,
            )
        # weekly and export are wired up in later build steps (spec Section 12).
        logger.info("mode %r not implemented yet", args.mode)
        return 0
    except Exception:
        logger.exception("unhandled error in %s run", args.mode)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
