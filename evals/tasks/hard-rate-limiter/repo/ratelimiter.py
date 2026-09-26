"""Rate limiters for the API gateway (see gateway.py).

Both limiters share one interface (RateLimiter): a single method

    allow(key: str) -> bool

which returns True and *records* the request (consumes a token / logs the
timestamp) if the request for `key` is allowed right now, or returns False
(and records nothing) if it must be rejected. Every call has a side effect
whether it returns True or False is checked in isolation -- there is no
separate "peek" method.

Each limiter is constructed with a `default_limit` config plus an optional
`overrides: dict[str, tuple]` mapping specific keys to their own config, so
different API keys (e.g. a "premium" tier) can get different limits from the
same limiter instance. Keys not present in `overrides` use the default.
State (tokens remaining, timestamps logged) is tracked per key and keys never
share state with each other.

Both limiters take an injected Clock (see clock.py) instead of reading the
wall clock directly, so behavior is fully deterministic under test.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from clock import Clock


class RateLimitExceeded(Exception):
    """Raised by Gateway when a request is rejected by the limiter."""


class RateLimiter(ABC):
    @abstractmethod
    def allow(self, key: str) -> bool:
        """Return True and record the request, or False and record nothing."""
        raise NotImplementedError


class TokenBucketLimiter(RateLimiter):
    """Classic token-bucket limiter.

    Each key has its own bucket holding up to `capacity` tokens, starting
    *full* (capacity tokens available) the first time a key is seen. Tokens
    refill continuously at `refill_rate` tokens/second (fractional refill is
    allowed -- don't round down between calls), capped at `capacity`.

    allow(key):
      - refill the bucket for `key` based on elapsed time since it was last
        touched (first touch = "now", i.e. no refill on first call),
      - if the bucket has >= 1.0 token available, subtract exactly 1.0 and
        return True,
      - otherwise leave the bucket as-is (still refilled) and return False.

    overrides maps key -> (capacity, refill_rate) for keys that don't use
    the default config.
    """

    def __init__(
        self,
        capacity: float,
        refill_rate: float,
        clock: Clock,
        *,
        overrides: dict[str, tuple[float, float]] | None = None,
    ) -> None:
        raise NotImplementedError

    def allow(self, key: str) -> bool:
        raise NotImplementedError


class SlidingWindowLimiter(RateLimiter):
    """Sliding-window-log limiter.

    Each key keeps a log of the timestamps of its allowed requests within the
    trailing `window_seconds`. A timestamp is considered "expired" (and
    dropped from the log) once `now - timestamp >= window_seconds` -- i.e. a
    request made *exactly* window_seconds ago no longer counts against the
    current window.

    allow(key):
      - drop expired timestamps from key's log,
      - if the number of remaining (non-expired) timestamps is < `limit`,
        append `now` to the log and return True,
      - otherwise return False (log unchanged).

    overrides maps key -> (limit, window_seconds) for keys that don't use
    the default config.
    """

    def __init__(
        self,
        limit: int,
        window_seconds: float,
        clock: Clock,
        *,
        overrides: dict[str, tuple[int, float]] | None = None,
    ) -> None:
        raise NotImplementedError

    def allow(self, key: str) -> bool:
        raise NotImplementedError
