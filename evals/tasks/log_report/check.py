"""Grader for log_report.

Expected values are hardcoded (computed independently from the pristine
access.log at task-authoring time) rather than re-derived from the workdir's
access.log, so a checker bug can't silently agree with a wrong report.
"""
import json
import os
import sys

WORKDIR = os.getcwd()
REPORT_FILE = os.path.join(WORKDIR, "report.json")

EXPECTED_STATUS_COUNTS = {"200": 39, "500": 3, "401": 2, "304": 1, "404": 4, "403": 1}
EXPECTED_TOP_PATHS = [
    {"path": "/index.html", "count": 12},
    {"path": "/about", "count": 9},
    {"path": "/api/data", "count": 7},
]


def fail(msg):
    print(f"FAIL: {msg}")
    sys.exit(1)


def main():
    if not os.path.isfile(REPORT_FILE):
        fail("report.json was not created")
    with open(REPORT_FILE, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            fail(f"report.json is not valid JSON: {e}")

    if not isinstance(data, dict):
        fail("report.json's top level must be a JSON object")

    if "status_counts" not in data or "top_paths" not in data:
        fail(f"report.json must have 'status_counts' and 'top_paths' keys, got: {list(data.keys())}")

    status_counts = data["status_counts"]
    if not isinstance(status_counts, dict):
        fail("'status_counts' must be an object")
    normalized = {str(k): v for k, v in status_counts.items()}
    if normalized != EXPECTED_STATUS_COUNTS:
        fail(f"status_counts mismatch: got {normalized}, expected {EXPECTED_STATUS_COUNTS}")

    top_paths = data["top_paths"]
    if not isinstance(top_paths, list) or len(top_paths) != 3:
        fail(f"'top_paths' must be a list of exactly 3 entries, got: {top_paths!r}")

    for i, (entry, expected) in enumerate(zip(top_paths, EXPECTED_TOP_PATHS)):
        if not isinstance(entry, dict) or "path" not in entry or "count" not in entry:
            fail(f"top_paths[{i}] must be an object with 'path' and 'count', got: {entry!r}")
        if entry["path"] != expected["path"] or int(entry["count"]) != expected["count"]:
            fail(f"top_paths[{i}] mismatch: got {entry}, expected {expected}")

    print("PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
