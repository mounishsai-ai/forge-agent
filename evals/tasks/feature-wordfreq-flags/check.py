import os
import subprocess
import sys
import tempfile


def run_cli(cwd, args):
    return subprocess.run(
        [sys.executable, "wordfreq.py"] + args,
        cwd=cwd, capture_output=True, text=True, timeout=30,
    )


def main():
    cwd = os.getcwd()

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "test_wordfreq.py", "-q"],
        cwd=cwd, capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print("Visible test test_wordfreq.py did not pass:")
        print(result.stdout[-2000:])
        print(result.stderr[-2000:])
        sys.exit(1)

    with tempfile.TemporaryDirectory() as td:
        text_path = os.path.join(td, "tie.txt")
        with open(text_path, "w", encoding="utf-8") as f:
            f.write("b b a a c")

        # Default: descending count, alphabetical tiebreak.
        result = run_cli(cwd, [text_path])
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "a\t2\nb\t2\nc\t1", f"default order wrong: {result.stdout!r}"

        # --reverse: ascending count, alphabetical tiebreak (unchanged direction).
        result = run_cli(cwd, [text_path, "--reverse"])
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "c\t1\na\t2\nb\t2", f"--reverse order wrong: {result.stdout!r}"

        # --limit N: only first N lines of the (default) sort.
        result = run_cli(cwd, [text_path, "--limit", "2"])
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "a\t2\nb\t2", f"--limit 2 wrong: {result.stdout!r}"

        # --reverse combined with --limit.
        result = run_cli(cwd, [text_path, "--reverse", "--limit", "1"])
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "c\t1", f"--reverse --limit 1 wrong: {result.stdout!r}"

        # --limit larger than available lines just prints everything.
        result = run_cli(cwd, [text_path, "--limit", "100"])
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "a\t2\nb\t2\nc\t1", f"--limit 100 wrong: {result.stdout!r}"

        # --limit 0 prints nothing.
        result = run_cli(cwd, [text_path, "--limit", "0"])
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "", f"--limit 0 should print nothing: {result.stdout!r}"

        # Bigger file with a larger distinct-word count to sanity check --reverse --limit together.
        big_path = os.path.join(td, "big.txt")
        with open(big_path, "w", encoding="utf-8") as f:
            f.write("the quick brown fox jumps over the lazy dog the dog barks at the fox")
        result = run_cli(cwd, [big_path, "--reverse", "--limit", "3"])
        assert result.returncode == 0, result.stderr
        lines = result.stdout.strip().split("\n")
        assert len(lines) == 3, f"expected 3 lines, got: {lines}"
        # Least frequent (count 1) words come first, alphabetically.
        assert lines[0] == "at\t1", f"unexpected first line: {lines[0]!r}"
        assert lines[1] == "barks\t1", f"unexpected second line: {lines[1]!r}"
        assert lines[2] == "brown\t1", f"unexpected third line: {lines[2]!r}"

    print("OK")


if __name__ == "__main__":
    main()
