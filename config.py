"""Loading of config.yaml, profile.yaml and .env — with clear failures."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent


class ConfigError(Exception):
    pass


def load_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"missing required file: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ConfigError(f"{path} did not parse to a mapping")
    return data


def load_config(root: Path = ROOT) -> dict:
    return load_yaml(root / "config.yaml")


def load_profile(root: Path = ROOT) -> dict:
    return load_yaml(root / "profile.yaml")


def load_env(root: Path = ROOT) -> dict:
    """Load .env and return the secrets Scout uses.

    Values are never logged. Missing values don't crash here — the modules
    that need them degrade loudly instead (spec 13: no silent failure, but
    one broken piece never kills the run).
    """
    load_dotenv(root / ".env")
    return {
        "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
        "email_address": os.environ.get("EMAIL_ADDRESS", ""),
        "email_app_password": os.environ.get("EMAIL_APP_PASSWORD", ""),
    }


def source_cfg(cfg: dict, name: str) -> dict:
    return (cfg.get("sources") or {}).get(name) or {}


def source_enabled(cfg: dict, name: str) -> bool:
    return bool(source_cfg(cfg, name).get("enabled", False))
