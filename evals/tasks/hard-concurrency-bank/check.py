"""Hidden grader for hard-concurrency-bank.

Runs bank.py's visible tests, then stress-tests Bank.transfer() under heavy
concurrent, bidirectional load and checks: (a) total balance conservation,
(b) no deadlock/hang, (c) no negative balances.

Deadlock is detected without ever risking an actual hang: threads are
daemon threads and we join against one shared wall-clock deadline. If
anything is still alive past the deadline we declare failure and hard-exit
the process immediately (works even if some threads are stuck holding
locks forever).
"""
import os
import random
import subprocess
import sys
import threading
import time

TIMEOUT_KWARGS = dict(encoding="utf-8", errors="replace")


def run_visible_tests(cwd):
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "test_bank.py", "-q"],
        cwd=cwd, capture_output=True, timeout=30, **TIMEOUT_KWARGS,
    )
    if result.returncode != 0:
        print("Visible test test_bank.py did not pass:")
        print(result.stdout[-2000:])
        print(result.stderr[-2000:])
        sys.exit(1)


def main():
    cwd = os.getcwd()
    run_visible_tests(cwd)

    # Make GIL-switching more frequent so lock-ordering bugs surface reliably
    # even in implementations that removed any artificial delay.
    try:
        sys.setswitchinterval(1e-5)
    except AttributeError:
        pass

    sys.path.insert(0, cwd)
    sys.modules.pop("bank", None)
    from bank import Bank, InsufficientFundsError

    N_ACCOUNTS = 8
    STARTING = 100000
    N_RANDOM_THREADS = 10
    RANDOM_TRANSFERS_PER_THREAD = 200
    PRESSURE_ITERS = 4000  # dedicated opposite-direction hammering

    bank = Bank()
    ids = [f"acct{i}" for i in range(N_ACCOUNTS)]
    for aid in ids:
        bank.open_account(aid, STARTING)
    total_before = bank.total_balance()

    errors = []
    errors_lock = threading.Lock()

    def record_error(exc):
        with errors_lock:
            errors.append(repr(exc))

    def random_worker(seed):
        rng = random.Random(seed)
        for _ in range(RANDOM_TRANSFERS_PER_THREAD):
            a, b = rng.sample(ids, 2)
            amount = rng.randint(1, 20)
            try:
                bank.transfer(a, b, amount)
            except InsufficientFundsError:
                pass
            except Exception as e:  # noqa: BLE001
                record_error(e)

    def pressure_worker(a, b):
        for _ in range(PRESSURE_ITERS):
            try:
                bank.transfer(a, b, 5)
            except InsufficientFundsError:
                pass
            except Exception as e:  # noqa: BLE001
                record_error(e)

    threads = []
    # Dedicated bidirectional pressure pairs: classic ABBA deadlock setup.
    threads.append(threading.Thread(target=pressure_worker, args=("acct0", "acct1"), daemon=True))
    threads.append(threading.Thread(target=pressure_worker, args=("acct1", "acct0"), daemon=True))
    threads.append(threading.Thread(target=pressure_worker, args=("acct2", "acct3"), daemon=True))
    threads.append(threading.Thread(target=pressure_worker, args=("acct3", "acct2"), daemon=True))
    for i in range(N_RANDOM_THREADS):
        threads.append(threading.Thread(target=random_worker, args=(i,), daemon=True))

    deadline = time.time() + 20
    for t in threads:
        t.start()
    for t in threads:
        remaining = max(0, deadline - time.time())
        t.join(timeout=remaining)

    alive = [t for t in threads if t.is_alive()]
    if alive:
        print(f"DEADLOCK/HANG suspected: {len(alive)} of {len(threads)} threads still "
              f"running after the deadline. This is a lock-ordering deadlock.", flush=True)
        os._exit(1)

    if errors:
        print("Unexpected errors during concurrent transfers:")
        print("\n".join(errors[:20]))
        sys.exit(1)

    total_after = bank.total_balance()
    if total_after != total_before:
        print(f"Money not conserved under concurrency: before={total_before} after={total_after} "
              f"(diff={total_after - total_before}). This is the race condition.")
        sys.exit(1)

    for aid in list(ids) + ["fees"]:
        bal = bank.get_balance(aid)
        if bal < 0:
            print(f"Account {aid} went negative: {bal}")
            sys.exit(1)

    print("OK")


if __name__ == "__main__":
    main()
