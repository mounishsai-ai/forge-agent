"""Hidden grader for hard-perf-dedupe.

Generates a fixed, deterministic 50,000-record dataset (no external
randomness - a hash-derived "base" string per group plus a small set of
punctuation/case/whitespace variations, so titles within a group are
always identical after normalize_title() and titles across groups are
never close to the similarity threshold). Runs the repo's
find_near_duplicates on it in a subprocess with a hard wall-clock timeout,
and compares the result against an independently-computed reference
grouping (not the repo's own code) for exact equality.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TIMEOUT_KWARGS = dict(encoding="utf-8", errors="replace")
TIME_LIMIT = 8  # seconds; the spec asks for well under 5s, this leaves grading slack

N_RECORDS = 50000
DUPES_PER_GROUP = 10

VARIATIONS = [
    lambda s: s,
    lambda s: s.upper(),
    lambda s: s.lower(),
    lambda s: s + "!!!",
    lambda s: s[: len(s) // 2] + "   " + s[len(s) // 2:],
    lambda s: "  " + s + "  ",
    lambda s: s[:3] + "-" + s[3:] + "-" + s[-3:],
    lambda s: s + ".",
    lambda s: "*" + s + "*",
    lambda s: (s[:5] + s[5].upper() + s[6:]) if len(s) > 5 else s,
]


def normalize_title(title):
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def make_base(i, length=28):
    s = hashlib.sha256(f"dedupe-base-{i}".encode()).hexdigest()
    while len(s) < length:
        s += hashlib.sha256(s.encode()).hexdigest()
    return s[:length]


def generate_records(n=N_RECORDS, dupes_per_group=DUPES_PER_GROUP):
    n_groups = n // dupes_per_group
    records = []
    for k in range(n):
        group = k % n_groups
        base = make_base(group)
        variant_fn = VARIATIONS[k % len(VARIATIONS)]
        title = variant_fn(base)
        records.append({"id": k, "title": title})
    # deterministic shuffle so input isn't group-sorted
    records.sort(key=lambda r: (r["id"] * 2654435761) % (n * 10 + 7))
    return records


def reference_grouping(records):
    buckets = {}
    for rec in records:
        key = normalize_title(rec["title"])
        buckets.setdefault(key, []).append(rec["id"])
    result = [sorted(ids) for ids in buckets.values()]
    result.sort(key=lambda g: g[0])
    return result


def run_visible_tests(cwd):
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "test_dedupe.py", "-q"],
        cwd=cwd, capture_output=True, timeout=30, **TIMEOUT_KWARGS,
    )
    if result.returncode != 0:
        print("Visible test test_dedupe.py did not pass:")
        print(result.stdout[-2000:])
        print(result.stderr[-2000:])
        sys.exit(1)


def main():
    cwd = os.getcwd()
    run_visible_tests(cwd)

    records = generate_records()
    expected = reference_grouping(records)

    with tempfile.TemporaryDirectory() as tmp:
        records_path = os.path.join(tmp, "records.json")
        output_path = os.path.join(tmp, "output.json")
        with open(records_path, "w", encoding="utf-8") as f:
            json.dump(records, f)

        driver = os.path.join(HERE, "_driver.py")
        start = time.time()
        try:
            result = subprocess.run(
                [sys.executable, driver, records_path, output_path],
                cwd=cwd, capture_output=True, timeout=TIME_LIMIT, **TIMEOUT_KWARGS,
            )
        except subprocess.TimeoutExpired:
            print(f"find_near_duplicates did not finish within {TIME_LIMIT}s on 50,000 "
                  f"records - still too slow.")
            sys.exit(1)
        elapsed = time.time() - start

        if result.returncode != 0:
            print(f"dedupe run crashed (exit {result.returncode}) after {elapsed:.2f}s:")
            print(result.stdout[-2000:])
            print(result.stderr[-2000:])
            sys.exit(1)

        if not os.path.exists(output_path):
            print("driver did not produce an output file")
            sys.exit(1)

        with open(output_path, "r", encoding="utf-8") as f:
            actual = json.load(f)

    if actual != expected:
        n_expected, n_actual = len(expected), len(actual)
        print(f"Output differs from the reference grouping "
              f"({n_expected} expected groups vs {n_actual} actual groups).")
        for e, a in zip(expected, actual):
            if e != a:
                print(f"first mismatch: expected {e} got {a}")
                break
        sys.exit(1)

    print(f"OK ({elapsed:.2f}s)")


if __name__ == "__main__":
    main()
