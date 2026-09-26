"""Grader for find_jwt_leeway.

Expects answer.txt to contain "function_name,seconds" where function_name is
(or ends with, e.g. "app.auth.validate_jwt_expiry") validate_jwt_expiry, and
seconds is 30 (the DEFAULT_LEEWAY_SECONDS in app/auth.py). Decoys in the repo
(validate_session_expiry=60, validate_permission_expiry=15,
config/settings.py's unused JWT_LEEWAY_SECONDS=300) should trip up a shallow grep.
"""
import os
import re
import sys

WORKDIR = os.getcwd()
ANSWER_FILE = os.path.join(WORKDIR, "answer.txt")

EXPECTED_FUNC = "validate_jwt_expiry"
EXPECTED_SECONDS = 30.0


def fail(msg):
    print(f"FAIL: {msg}")
    sys.exit(1)


def main():
    if not os.path.isfile(ANSWER_FILE):
        fail("answer.txt was not created")
    with open(ANSWER_FILE, encoding="utf-8") as f:
        text = f.read().strip()
    if not text:
        fail("answer.txt is empty")

    line = text.splitlines()[0].strip()
    parts = [p.strip() for p in line.split(",")]
    if len(parts) != 2:
        fail(f"expected 'function_name,seconds' but got: {line!r}")

    func_raw, seconds_raw = parts
    func_name = func_raw.split(".")[-1].strip("`'\" ").lower()

    if func_name != EXPECTED_FUNC.lower():
        fail(f"wrong function name: got {func_raw!r}, expected something ending in {EXPECTED_FUNC!r}")

    m = re.search(r"-?\d+(\.\d+)?", seconds_raw)
    if not m:
        fail(f"could not parse a number of seconds from: {seconds_raw!r}")
    try:
        seconds_val = float(m.group())
    except ValueError:
        fail(f"could not parse a number of seconds from: {seconds_raw!r}")

    if seconds_val != EXPECTED_SECONDS:
        fail(f"wrong leeway: got {seconds_val}, expected {EXPECTED_SECONDS}")

    print("PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
