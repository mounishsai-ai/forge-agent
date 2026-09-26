"""A few basic sanity checks. The hidden grader is much stricter about exact
boundary timing and per-key isolation -- passing this file is necessary but
not sufficient."""
from clock import Clock
from ratelimiter import TokenBucketLimiter, SlidingWindowLimiter


class ManualClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def now(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def test_token_bucket_basic():
    clock = ManualClock()
    limiter = TokenBucketLimiter(capacity=2, refill_rate=1.0, clock=clock)
    assert limiter.allow("a") is True
    assert limiter.allow("a") is True
    assert limiter.allow("a") is False  # bucket empty


def test_token_bucket_refill():
    clock = ManualClock()
    limiter = TokenBucketLimiter(capacity=1, refill_rate=1.0, clock=clock)
    assert limiter.allow("a") is True
    assert limiter.allow("a") is False
    clock.advance(1.0)
    assert limiter.allow("a") is True


def test_sliding_window_basic():
    clock = ManualClock()
    limiter = SlidingWindowLimiter(limit=2, window_seconds=10.0, clock=clock)
    assert limiter.allow("a") is True
    assert limiter.allow("a") is True
    assert limiter.allow("a") is False
    clock.advance(10.0)
    assert limiter.allow("a") is True


def test_per_key_isolation():
    clock = ManualClock()
    limiter = TokenBucketLimiter(capacity=1, refill_rate=1.0, clock=clock)
    assert limiter.allow("a") is True
    assert limiter.allow("b") is True  # separate bucket, unaffected by "a"
