"""Logging — append Seed Audio generation entries to the shared JSON log."""

import json
import os

from . import config


def append(entry: dict):
    """Append a generation entry to dub_log.json."""
    entries = []
    if os.path.exists(config.LOG_FILE):
        try:
            with open(config.LOG_FILE, "r") as f:
                entries = json.load(f)
                if not isinstance(entries, list):
                    entries = [entries]
        except Exception:
            entries = []
    entries.append(entry)
    with open(config.LOG_FILE, "w") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)