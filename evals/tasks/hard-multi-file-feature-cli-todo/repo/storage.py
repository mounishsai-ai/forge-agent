"""JSON-file persistence for tasks."""
import json
import os

from models import Task


def load_tasks(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [Task.from_dict(d) for d in data]


def save_tasks(path, tasks):
    with open(path, "w", encoding="utf-8") as f:
        json.dump([t.to_dict() for t in tasks], f, indent=2)


def next_id(tasks):
    return max((t.id for t in tasks), default=0) + 1
