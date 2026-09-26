"""Hidden grader for hard-bug-hunt-from-logs."""
import os
import subprocess
import sys

TIMEOUT_KWARGS = dict(encoding="utf-8", errors="replace")


def run_visible_tests(cwd):
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "test_pipeline.py", "-q"],
        cwd=cwd, capture_output=True, timeout=30, **TIMEOUT_KWARGS,
    )
    if result.returncode != 0:
        print("Visible test test_pipeline.py did not pass:")
        print(result.stdout[-2000:])
        print(result.stderr[-2000:])
        sys.exit(1)


def fail(msg):
    print(msg)
    sys.exit(1)


def big_items():
    return [
        {"sku": "A1", "quantity": 2, "unit_price": 10.0},
        {"sku": "B2", "quantity": 1, "unit_price": 5.0},
        {"sku": "C3", "quantity": 3, "unit_price": 8.0},
    ]


def main():
    cwd = os.getcwd()
    run_visible_tests(cwd)

    sys.path.insert(0, cwd)
    for m in ("models", "orders", "tagging", "pricing", "inventory", "shipping", "pipeline"):
        sys.modules.pop(m, None)
    from orders import build_order
    from pipeline import process_batch

    # 1. Direct regression test on the actual root cause: build_order() must
    #    never hand out a shared mutable list across calls.
    o1 = build_order("R1", big_items())
    o1.tags.append("polluted")
    o2 = build_order("R2", big_items())
    if o2.tags != []:
        fail(f"build_order() is sharing state across calls: expected a fresh empty "
             f"tags list for a new order, got {o2.tags!r} after mutating a previous "
             f"order's tags")

    # 2. Reproduce the incident at scale: a long run of large (>=3 item) orders
    #    must not raise, and no order's discount should be affected by orders
    #    processed earlier in the same batch.
    n = 25
    batch = [{"order_id": f"ORD-{i}", "items": big_items()} for i in range(n)]
    try:
        results = process_batch(batch)
    except Exception as e:  # noqa: BLE001
        fail(f"process_batch raised on a batch of {n} large orders (this is the "
             f"incident): {e!r}")

    expected_total = round(49.0 * 0.95, 2)
    for i, r in enumerate(results):
        if r["tags"] != ["bulk"]:
            fail(f"order index {i} ({r['order_id']}) should have exactly one 'bulk' "
                 f"tag from its own qualifying items, got {r['tags']!r}")
        if r["total"] != expected_total:
            fail(f"order index {i} ({r['order_id']}) expected total {expected_total}, "
                 f"got {r['total']} - its price is being affected by other orders "
                 f"in the batch")

    print("OK")


if __name__ == "__main__":
    main()
