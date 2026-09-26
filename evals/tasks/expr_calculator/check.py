"""Grader for expr_calculator.

Runs evaluate() from the workdir's calc.py, in a child process (with a timeout,
so a broken/infinite parser can't hang the checker), against many valid and
malformed expressions well beyond the visible test_calc.py, and rejects any
solution that uses eval()/exec()/literal_eval instead of writing a real parser.
"""
import json
import os
import re
import subprocess
import sys

WORKDIR = os.getcwd()
CALC_PATH = os.path.join(WORKDIR, "calc.py")

VALID_CASES = [
    ("1+2", 3),
    ("2+3*4", 14),
    ("(2+3)*4", 20),
    ("2-3-4", -5),
    ("20/4/5", 1.0),
    ("-3+5", 2),
    ("-(3+2)", -5),
    ("3 - -2", 5),
    (" 1 + 2 * 3 ", 7),
    ("10/2", 5.0),
    ("7/2", 3.5),
    ("((1+2)*(3+4))", 21),
    ("2.5+1.5", 4.0),
    ("--3", 3),
    ("-+3", -3),
    ("-2*3", -6),
    ("2*-3", -6),
    ("0-0", 0),
    ("100", 100),
    ("(((5)))", 5),
    ("1.5*2", 3.0),
    ("9/3/3", 1.0),
    ("2+2+2+2", 8),
    ("10-2*3", 4),
    ("(10-2)*3", 24),
]

ERROR_CASES = [
    "",
    "   ",
    "()",
    "(1+2",
    "1+2)",
    "1 2",
    "2(3)",
    "abc",
    "1+",
    "1/0",
    "*3",
    "3*",
    "1++",
    "1@2",
    "5/$2",
]


def fail(msg):
    print(f"FAIL: {msg}")
    sys.exit(1)


def main():
    if not os.path.isfile(CALC_PATH):
        fail("calc.py is missing")
    with open(CALC_PATH, encoding="utf-8") as f:
        src = f.read()

    if re.search(r"\beval\s*\(", src) or re.search(r"\bexec\s*\(", src) or "literal_eval" in src:
        fail("calc.py must not use eval()/exec()/ast.literal_eval — write a real parser")

    probe = r"""
import sys, json
sys.path.insert(0, r"%s")
from calc import evaluate

valid_cases = %r
error_cases = %r
out = {"valid": [], "error": []}
for expr, _ in valid_cases:
    try:
        out["valid"].append({"ok": evaluate(expr)})
    except Exception as e:
        out["valid"].append({"err": type(e).__name__})
for expr in error_cases:
    try:
        out["error"].append({"ok": evaluate(expr)})
    except Exception as e:
        out["error"].append({"err": type(e).__name__})
print(json.dumps(out))
""" % (WORKDIR.replace("\\", "\\\\"), VALID_CASES, ERROR_CASES)

    try:
        result = subprocess.run([sys.executable, "-c", probe], cwd=WORKDIR,
                                 capture_output=True, text=True, timeout=25)
    except subprocess.TimeoutExpired:
        fail("evaluating expressions timed out (possible infinite loop)")

    if result.returncode != 0:
        fail(f"importing/running calc.py raised an error:\n{result.stderr[-1500:]}")

    try:
        out = json.loads(result.stdout.strip().splitlines()[-1])
    except Exception:
        fail(f"could not parse output: {result.stdout!r} {result.stderr!r}")

    for (expr, expected), actual in zip(VALID_CASES, out["valid"]):
        if "err" in actual:
            fail(f"evaluate({expr!r}) raised {actual['err']}, expected {expected}")
        got = actual["ok"]
        if not isinstance(got, (int, float)) or abs(got - expected) > 1e-9:
            fail(f"evaluate({expr!r}) = {got!r}, expected {expected}")

    for expr, actual in zip(ERROR_CASES, out["error"]):
        if "err" not in actual:
            fail(f"evaluate({expr!r}) should raise ValueError, but returned {actual.get('ok')!r}")
        if actual["err"] != "ValueError":
            fail(f"evaluate({expr!r}) raised {actual['err']}, expected ValueError")

    # sanity: also run the visible tests to make sure the solution isn't inconsistent with them
    try:
        pytest_result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "test_calc.py"],
            cwd=WORKDIR, capture_output=True, text=True, timeout=25,
        )
    except subprocess.TimeoutExpired:
        fail("running the visible test_calc.py timed out")
    if pytest_result.returncode != 0:
        fail("visible test_calc.py does not pass:\n" + (pytest_result.stdout + pytest_result.stderr)[-1500:])

    print("PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
