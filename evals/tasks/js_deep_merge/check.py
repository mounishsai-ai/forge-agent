"""Grader for js_deep_merge. Runs check_assertions.js (a Node script living next to
this file, not in repo/, so the agent never sees it) against the workdir's utils.js.
"""
import os
import subprocess
import sys

WORKDIR = os.getcwd()
HERE = os.path.dirname(os.path.abspath(__file__))
UTILS_PATH = os.path.join(WORKDIR, "utils.js")
ASSERTIONS_SCRIPT = os.path.join(HERE, "check_assertions.js")


def fail(msg):
    print(f"FAIL: {msg}")
    sys.exit(1)


def main():
    if not os.path.isfile(UTILS_PATH):
        fail("utils.js is missing from the work dir")

    try:
        result = subprocess.run(
            ["node", ASSERTIONS_SCRIPT, UTILS_PATH],
            capture_output=True, text=True, timeout=20,
        )
    except FileNotFoundError:
        fail("could not find `node` on PATH")
    except subprocess.TimeoutExpired:
        fail("node assertion script timed out")

    print(result.stdout)
    if result.returncode != 0:
        fail("one or more deepMerge checks failed:\n" + result.stderr[-1500:])

    print("PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
