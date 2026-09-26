"""Tiny stand-in for an API gateway's request-handling path.

`Gateway.handle(key)` is what a request handler would call before doing real
work: it consults the injected limiter and either returns "OK" or raises
RateLimitExceeded. This file is intentionally small; the interesting logic
lives in ratelimiter.py.
"""
from __future__ import annotations

from ratelimiter import RateLimiter, RateLimitExceeded


class Gateway:
    def __init__(self, limiter: RateLimiter) -> None:
        self.limiter = limiter

    def handle(self, key: str) -> str:
        if not self.limiter.allow(key):
            raise RateLimitExceeded(f"rate limit exceeded for key {key!r}")
        return "OK"
