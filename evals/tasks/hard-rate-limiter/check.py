import os
import subprocess
import sys


def main():
    cwd = os.getcwd()

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "test_ratelimiter.py", "-q"],
        cwd=cwd, capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print("Visible test test_ratelimiter.py did not pass:")
        print(result.stdout[-2000:])
        print(result.stderr[-2000:])
        sys.exit(1)

    sys.path.insert(0, cwd)
    for mod in ("clock", "ratelimiter", "gateway"):
        sys.modules.pop(mod, None)
    from ratelimiter import TokenBucketLimiter, SlidingWindowLimiter, RateLimitExceeded
    from gateway import Gateway

    class FakeClock:
        def __init__(self, t=0.0):
            self.t = t

        def now(self):
            return self.t

        def advance(self, dt):
            self.t += dt

    failures = []

    def check(label, cond):
        if not cond:
            failures.append(label)

    # ---- Token bucket: exact allow/deny sequence at boundaries ----
    clock = FakeClock()
    tb = TokenBucketLimiter(capacity=3, refill_rate=1.0, clock=clock)  # 1 token/sec
    # Starts full: 3 allowed immediately, 4th denied.
    check("tb.1", tb.allow("k") is True)
    check("tb.2", tb.allow("k") is True)
    check("tb.3", tb.allow("k") is True)
    check("tb.4 (bucket empty)", tb.allow("k") is False)
    # 0.5s later: 0.5 tokens refilled, still < 1 -> denied.
    clock.advance(0.5)
    check("tb.5 (partial refill, still <1)", tb.allow("k") is False)
    # another 0.5s (elapsed 1.0s total since last consume): exactly 1 token -> allowed.
    clock.advance(0.5)
    check("tb.6 (exactly 1 token at boundary)", tb.allow("k") is True)
    check("tb.7 (consumed again immediately)", tb.allow("k") is False)
    # Let it sit for 10s -> refill caps at capacity (3), not unbounded.
    clock.advance(10.0)
    check("tb.8", tb.allow("k") is True)
    check("tb.9", tb.allow("k") is True)
    check("tb.10", tb.allow("k") is True)
    check("tb.11 (capped at capacity, not 10)", tb.allow("k") is False)

    # Per-key isolation: a fresh key starts full independent of "k".
    check("tb.12 (fresh key independent)", tb.allow("other") is True)

    # Per-key overrides: "vip" gets a bigger bucket/rate.
    clock2 = FakeClock()
    tb2 = TokenBucketLimiter(
        capacity=1, refill_rate=1.0, clock=clock2, overrides={"vip": (5, 1.0)}
    )
    check("tb.13 (default key limited to 1)", tb2.allow("plain") is True)
    check("tb.14 (default key now denied)", tb2.allow("plain") is False)
    vip_allows = [tb2.allow("vip") for _ in range(5)]
    check("tb.15 (vip override capacity=5)", vip_allows == [True] * 5)
    check("tb.16 (vip bucket now empty)", tb2.allow("vip") is False)

    # ---- Sliding window: exact allow/deny sequence at boundaries ----
    clock3 = FakeClock()
    sw = SlidingWindowLimiter(limit=3, window_seconds=10.0, clock=clock3)
    check("sw.1", sw.allow("k") is True)
    clock3.advance(2.0)
    check("sw.2", sw.allow("k") is True)
    clock3.advance(2.0)
    check("sw.3", sw.allow("k") is True)
    check("sw.4 (limit reached within window)", sw.allow("k") is False)
    # Advance so the FIRST request (t=0) is exactly at the window edge (t=10):
    # now - 0 == 10 -> expired, so one slot frees up.
    clock3.advance(6.0)  # now t=10.0
    check("sw.5 (oldest exactly expires at boundary)", sw.allow("k") is True)
    check("sw.6 (window full again)", sw.allow("k") is False)

    # Per-key isolation for sliding window.
    check("sw.7 (different key unaffected)", sw.allow("other") is True)

    # Per-key overrides for sliding window.
    clock4 = FakeClock()
    sw2 = SlidingWindowLimiter(
        limit=1, window_seconds=5.0, clock=clock4, overrides={"vip": (3, 5.0)}
    )
    check("sw.8 (default limit=1)", sw2.allow("plain") is True)
    check("sw.9 (default now denied)", sw2.allow("plain") is False)
    vip_sw = [sw2.allow("vip") for _ in range(3)]
    check("sw.10 (vip override limit=3)", vip_sw == [True] * 3)
    check("sw.11 (vip window full)", sw2.allow("vip") is False)

    # ---- Gateway integration ----
    clock5 = FakeClock()
    gw = Gateway(TokenBucketLimiter(capacity=1, refill_rate=1.0, clock=clock5))
    check("gw.1 (first request OK)", gw.handle("x") == "OK")
    try:
        gw.handle("x")
        failures.append("gw.2 (expected RateLimitExceeded)")
    except RateLimitExceeded:
        pass
    except Exception as e:
        failures.append(f"gw.2 (wrong exception type: {e!r})")

    if failures:
        print("FAILED checks:")
        for f in failures:
            print(" -", f)
        sys.exit(1)

    print("OK")


if __name__ == "__main__":
    main()
