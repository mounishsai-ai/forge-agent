"""Deliberately-buggy variant of inventory.py, used only by check.py to
confirm the fixed test suite still catches real regressions (i.e. wasn't
"fixed" by weakening the assertions into no-ops)."""
from __future__ import annotations

import json
import os
import time


class Item:
    def __init__(self, name: str, tags, created_at: float | None = None) -> None:
        self.name = name
        self.tags = set(tags)
        self.created_at = created_at if created_at is not None else time.time()

    def age_seconds(self, now: float | None = None) -> float:
        if now is None:
            now = time.time()
        # BUG: sign flipped.
        return self.created_at - now


def tag_summary(items) -> set:
    # BUG: only considers the first item, silently drops the rest.
    tags: set = set()
    for item in items[:1]:
        tags |= item.tags
    return tags


DATA_FILE = "inventory_data.json"


def save_items(items, path: str = DATA_FILE) -> None:
    # BUG: drops the "name" field entirely.
    with open(path, "w", encoding="utf-8") as f:
        json.dump([{"tags": sorted(i.tags)} for i in items], f)


def load_items(path: str = DATA_FILE):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    # BUG: name defaults to "" for everything since save_items dropped it.
    return [Item(name=r.get("name", ""), tags=set(r["tags"])) for r in raw]
