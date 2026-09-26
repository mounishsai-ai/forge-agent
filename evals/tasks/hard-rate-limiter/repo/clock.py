"""Injectable clock so rate limiters can be tested without real wall-clock delays.

Any object with a ``now() -> float`` method (seconds, monotonically non-decreasing)
satisfies this Protocol. Production code uses SystemClock; tests use a fake clock
that they advance manually.
"""
from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float:
        """Return the current time in seconds (monotonic, arbitrary epoch)."""
        ...


class SystemClock:
    """Real clock backed by time.monotonic()."""

    def now(self) -> float:
        return time.monotonic()
