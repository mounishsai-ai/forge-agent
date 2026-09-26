"""Small inventory helper module used by test_inventory.py.

This module is not the bug -- see test_inventory.py for what's actually
wrong with the suite that uses it.
"""
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
        """Seconds since this item was created. `now` can be passed
        explicitly (e.g. in tests) instead of relying on the real clock."""
        if now is None:
            now = time.time()
        return now - self.created_at


def tag_summary(items) -> set:
    """Union of all tags across `items`. Returns a set -- iteration order
    is not guaranteed (Python randomizes string hashing per process), so
    callers must not depend on any particular order."""
    tags: set = set()
    for item in items:
        tags |= item.tags
    return tags


DATA_FILE = "inventory_data.json"


def save_items(items, path: str = DATA_FILE) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump([{"name": i.name, "tags": sorted(i.tags)} for i in items], f)


def load_items(path: str = DATA_FILE):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return [Item(name=r["name"], tags=set(r["tags"])) for r in raw]
