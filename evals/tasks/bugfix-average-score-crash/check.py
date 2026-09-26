import json
import os
import subprocess
import sys
import tempfile


def run_cli(cwd, json_path):
    return subprocess.run(
        [sys.executable, "report.py", json_path],
        cwd=cwd, capture_output=True, text=True, timeout=30,
    )


def main():
    cwd = os.getcwd()

    # CLI must not crash on an empty record list.
    result = run_cli(cwd, "empty.json")
    if result.returncode != 0:
        print("report.py empty.json crashed:")
        print(result.stdout[-1500:])
        print(result.stderr[-1500:])
        sys.exit(1)
    if "Average score: 0.00" not in result.stdout:
        print(f"Expected 'Average score: 0.00' for empty.json, got: {result.stdout!r}")
        sys.exit(1)

    # CLI must not crash when a record is missing "score" (treated as 0).
    result = run_cli(cwd, "partial.json")
    if result.returncode != 0:
        print("report.py partial.json crashed:")
        print(result.stdout[-1500:])
        print(result.stderr[-1500:])
        sys.exit(1)
    expected = (90 + 70 + 0) / 3
    if f"Average score: {expected:.2f}" not in result.stdout:
        print(f"Expected 'Average score: {expected:.2f}' for partial.json, got: {result.stdout!r}")
        sys.exit(1)

    # Exercise the function directly for edge cases not covered by the CLI.
    sys.path.insert(0, cwd)
    sys.modules.pop("scores", None)
    from scores import average_score

    assert average_score([]) == 0.0, "empty list should be 0.0"
    assert average_score([{"score": 5}]) == 5.0
    assert average_score([{"score": 10}, {"name": "no score"}]) == 5.0
    assert average_score([{"name": "a"}, {"name": "b"}]) == 0.0, "all missing scores -> 0.0"

    # A fresh record list with a mix, written to a temp file, run through the CLI.
    with tempfile.TemporaryDirectory() as td:
        mixed_path = os.path.join(td, "mixed.json")
        with open(mixed_path, "w", encoding="utf-8") as f:
            json.dump([{"score": 100}, {"score": 0}, {"other": 1}, {"score": 50}], f)
        result = run_cli(cwd, mixed_path)
        if result.returncode != 0:
            print("report.py crashed on mixed temp data:")
            print(result.stderr[-1500:])
            sys.exit(1)
        expected_mixed = (100 + 0 + 0 + 50) / 4
        if f"Average score: {expected_mixed:.2f}" not in result.stdout:
            print(f"Expected 'Average score: {expected_mixed:.2f}', got: {result.stdout!r}")
            sys.exit(1)

    print("OK")


if __name__ == "__main__":
    main()
