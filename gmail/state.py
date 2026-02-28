"""Persistent review-state: tracks message IDs the user has already handled."""

import json
import os

REVIEWED_FILE = "reviewed.json"


def load_reviewed() -> set:
    if not os.path.exists(REVIEWED_FILE):
        return set()
    with open(REVIEWED_FILE) as f:
        try:
            return set(json.load(f))
        except (json.JSONDecodeError, ValueError):
            return set()


def mark_reviewed(ids) -> None:
    existing = load_reviewed()
    existing.update(ids)
    with open(REVIEWED_FILE, "w") as f:
        json.dump(sorted(existing), f)


def clear_reviewed() -> None:
    if os.path.exists(REVIEWED_FILE):
        os.remove(REVIEWED_FILE)


def count_reviewed() -> int:
    return len(load_reviewed())
