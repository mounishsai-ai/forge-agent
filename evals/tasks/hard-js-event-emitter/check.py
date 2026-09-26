"""Hidden grader for hard-js-event-emitter."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TIMEOUT_KWARGS = dict(encoding="utf-8", errors="replace")


def main():
    cwd = os.getcwd()

    visible = subprocess.run(
        ["node", "emitter.test.js"], cwd=cwd, capture_output=True, timeout=20, **TIMEOUT_KWARGS,
    )
    if visible.returncode != 0:
        print("Visible test emitter.test.js did not pass:")
        print(visible.stdout[-2000:])
        print(visible.stderr[-2000:])
        sys.exit(1)

    hidden = subprocess.run(
        ["node", os.path.join(HERE, "hidden_test.js")],
        cwd=cwd, capture_output=True, timeout=20, **TIMEOUT_KWARGS,
    )
    print(hidden.stdout)
    if hidden.returncode != 0:
        print(hidden.stderr[-2000:])
        sys.exit(1)

    print("OK")


if __name__ == "__main__":
    main()
