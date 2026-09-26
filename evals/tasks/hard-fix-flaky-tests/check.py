import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
N_RUNS = 15
BANNED_SLEEP_CONFTEST = '''import time

def _banned_sleep(seconds):
    raise RuntimeError(
        "time.sleep() was called during the test suite -- tests must not depend "
        "on real elapsed wall-clock time; inject an explicit/fake clock instead."
    )

time.sleep = _banned_sleep
'''


def run_pytest(cwd, args, extra_env=None, timeout=30):
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "pytest"] + args,
        cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env,
    )


def collect_node_ids(cwd):
    result = run_pytest(cwd, ["test_inventory.py", "--collect-only", "-q"])
    ids = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("test_inventory.py::"):
            ids.append(line)
    return ids, result


def main():
    cwd = os.getcwd()
    failures = []

    node_ids, collect_result = collect_node_ids(cwd)
    if not node_ids:
        print("Could not collect any tests from test_inventory.py:")
        print(collect_result.stdout[-1500:])
        print(collect_result.stderr[-1500:])
        sys.exit(1)

    conftest_path = os.path.join(cwd, "conftest.py")
    had_conftest = os.path.exists(conftest_path)
    original_conftest = None
    if had_conftest:
        with open(conftest_path, encoding="utf-8") as f:
            original_conftest = f.read()

    try:
        # Append (don't clobber) our sleep-ban into whatever conftest the
        # agent may have added, so both apply.
        with open(conftest_path, "a", encoding="utf-8") as f:
            f.write("\n\n# --- injected by eval checker ---\n" + BANNED_SLEEP_CONFTEST)

        # ---- Run 15 times: shuffled test order + varying PYTHONHASHSEED,
        # with real time.sleep banned. Every run must pass. ----
        for i in range(N_RUNS):
            order = list(node_ids)
            random.Random(1000 + i).shuffle(order)
            result = run_pytest(cwd, order + ["-q"], extra_env={"PYTHONHASHSEED": str(i)})
            if result.returncode != 0:
                failures.append(
                    f"run {i} (PYTHONHASHSEED={i}) failed with order {order}:\n"
                    f"{result.stdout[-1200:]}\n{result.stderr[-500:]}"
                )
                break  # one detailed failure is enough
    finally:
        if had_conftest:
            with open(conftest_path, "w", encoding="utf-8") as f:
                f.write(original_conftest)
        else:
            try:
                os.remove(conftest_path)
            except OSError:
                pass

    if failures:
        print("FAILED: test suite is not deterministic under reordering/hash-seed variation:")
        for f in failures:
            print(f)
        sys.exit(1)

    # ---- The suite must still catch real regressions: swap in a
    # deliberately-buggy inventory.py and confirm at least one test fails. ----
    inventory_path = os.path.join(cwd, "inventory.py")
    with open(inventory_path, encoding="utf-8") as f:
        original_inventory = f.read()
    buggy_path = os.path.join(HERE, "buggy_inventory.py")
    with open(buggy_path, encoding="utf-8") as f:
        buggy_inventory = f.read()

    try:
        with open(inventory_path, "w", encoding="utf-8") as f:
            f.write(buggy_inventory)
        result = run_pytest(cwd, ["test_inventory.py", "-q"])
        if result.returncode == 0:
            print("FAILED: test suite still passes against a deliberately-buggy inventory.py")
            print("-- assertions were likely weakened instead of the flakiness being fixed.")
            print(result.stdout[-1500:])
            sys.exit(1)
    finally:
        with open(inventory_path, "w", encoding="utf-8") as f:
            f.write(original_inventory)

    print("OK")


if __name__ == "__main__":
    main()
