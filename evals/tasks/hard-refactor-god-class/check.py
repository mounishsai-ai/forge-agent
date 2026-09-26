import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN_DIR = os.path.join(HERE, "golden")


def main():
    cwd = os.getcwd()

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "test_report_generator.py", "-q"],
        cwd=cwd, capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print("Visible test test_report_generator.py did not pass:")
        print(result.stdout[-2000:])
        print(result.stderr[-2000:])
        sys.exit(1)

    failures = []

    def check(label, cond):
        if not cond:
            failures.append(label)

    # --- The class must actually have been split up. ---
    rg_path = os.path.join(cwd, "report_generator.py")
    if not os.path.isfile(rg_path):
        print("report_generator.py is missing")
        sys.exit(1)
    with open(rg_path, encoding="utf-8") as f:
        rg_lines = f.readlines()
    check(f"report_generator.py is under 150 lines (got {len(rg_lines)})", len(rg_lines) <= 150)

    other_modules = [
        fn for fn in os.listdir(cwd)
        if fn.endswith(".py")
        and fn not in ("report_generator.py",)
        and not fn.startswith("test_")
        and os.path.isfile(os.path.join(cwd, fn))
    ]
    check(
        f"at least 3 new modules exist alongside report_generator.py (found {other_modules})",
        len(other_modules) >= 3,
    )

    # --- Output must be byte-identical to golden files from the original
    # implementation, for every fixture and format. ---
    sys.path.insert(0, cwd)
    sys.modules.pop("report_generator", None)
    try:
        from report_generator import generate_report
    except Exception as e:
        print(f"could not import generate_report from report_generator: {e!r}")
        sys.exit(1)

    for fixture in ("small", "medium", "tie"):
        fixture_path = os.path.join(cwd, "fixtures", f"{fixture}.csv")
        for fmt, ext in (("csv", "csv"), ("html", "html")):
            golden_path = os.path.join(GOLDEN_DIR, f"{fixture}.{ext}")
            with open(golden_path, encoding="utf-8") as f:
                expected = f.read()
            try:
                actual = generate_report(fixture_path, fmt)
            except Exception as e:
                failures.append(f"{fixture}/{fmt}: generate_report raised {e!r}")
                continue
            check(f"{fixture}/{fmt} output matches golden byte-for-byte", actual == expected)

    # --- Error behavior (including exact message content) preserved. ---
    bad_path = os.path.join(cwd, "fixtures", "bad_quantity.csv")
    try:
        generate_report(bad_path, "csv")
        failures.append("bad_quantity.csv: expected ValueError, none raised")
    except ValueError as e:
        msg = str(e)
        check(f"bad_quantity error message preserved (got {msg!r})", "row 3" in msg and "quantity" in msg)
    except Exception as e:
        failures.append(f"bad_quantity.csv: wrong exception type {e!r}")

    if failures:
        print("FAILED checks:")
        for f in failures:
            print(" -", f)
        sys.exit(1)

    print("OK")


if __name__ == "__main__":
    main()
