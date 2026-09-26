"""Grader for rename_symbol.

Requires:
  1. The literal name `calc_total` no longer appears in any .py file in the work dir.
  2. `compute_total` exists and behavior of the whole mini app is unchanged, exercised
     via a child process (so a hang in edited code can't wedge this checker).
"""
import json
import os
import re
import subprocess
import sys

WORKDIR = os.getcwd()
SKIP_DIRS = {".git", ".forge", "__pycache__", ".pytest_cache"}


def iter_py_files():
    for root, dirs, files in os.walk(WORKDIR):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(root, f)


def fail(msg):
    print(f"FAIL: {msg}")
    sys.exit(1)


def main():
    name_re = re.compile(r"\bcalc_total\b")
    for path in iter_py_files():
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except (UnicodeDecodeError, OSError):
            continue
        if name_re.search(content):
            fail(f"old name 'calc_total' still present in {os.path.relpath(path, WORKDIR)}")

    probe = r"""
import sys, json
sys.path.insert(0, r"%s")
from core import compute_total
from orders import order_summary, order_summary_via_module
from report import generate_report, report_grand_total

orders = [
    {"id": 1, "items": [{"price": 10.0, "qty": 2}, {"price": 5.0, "qty": 1}]},
    {"id": 2, "items": [{"price": 3.5, "qty": 4}]},
]
out = {
    "summary1": order_summary(orders[0]),
    "summary2_via_module": order_summary_via_module(orders[1]),
    "report": generate_report(orders),
    "grand_total": report_grand_total(orders),
    "direct": compute_total([{"price": 1.0, "qty": 1}]),
}
print(json.dumps(out))
""" % WORKDIR.replace("\\", "\\\\")

    try:
        result = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=WORKDIR, capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        fail("importing/running the renamed project timed out")

    if result.returncode != 0:
        fail(f"running renamed project raised an error:\n{result.stderr[-1500:]}")

    try:
        out = json.loads(result.stdout.strip().splitlines()[-1])
    except Exception:
        fail(f"could not parse output: {result.stdout!r} {result.stderr!r}")

    expected = {
        "summary1": {"id": 1, "total": 25.0},
        "summary2_via_module": {"id": 2, "total": 14.0},
        "report": {"1": 25.0, "2": 14.0},
        "grand_total": 39.0,
        "direct": 1.0,
    }
    # json.dumps turns int dict keys into strings on the "report" field via json.loads on our side too
    report_norm = {str(k): v for k, v in out.get("report", {}).items()}
    checks = [
        (out.get("summary1") == expected["summary1"], "order_summary result wrong"),
        (out.get("summary2_via_module") == expected["summary2_via_module"], "order_summary_via_module result wrong"),
        (report_norm == expected["report"], f"generate_report result wrong: {report_norm}"),
        (out.get("grand_total") == expected["grand_total"], "report_grand_total result wrong"),
        (out.get("direct") == expected["direct"], "compute_total direct call result wrong"),
    ]
    for ok, msg in checks:
        if not ok:
            fail(msg)

    print("PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
