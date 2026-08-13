"""Rate limits and the model-spend kill-switch.

Two independent guards, both of which degrade honestly instead of erroring:

* per-IP token bucket on uploads — a burst of 5, refilling to 12/hour;
  a 429 carries Retry-After and the UI shows your remaining quota.
* a global daily budget of model calls — when it is spent, uploads flip
  to a labelled degraded mode while the precomputed gallery keeps working
  forever (it never needed a model in the first place).
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field

UPLOADS_PER_HOUR = 12
BURST = 5
DAILY_MODEL_BUDGET = int(os.environ.get("TALLYPROOF_DAILY_BUDGET", "300"))


@dataclass
class Bucket:
    tokens: float = BURST
    updated: float = field(default_factory=time.time)


class RateLimiter:
    """Token bucket with an atomic reserve-then-refund protocol.

    ``reserve`` checks AND decrements in one critical section — upload
    handlers run in a threadpool, so a check-here-spend-later split would
    let concurrent requests all pass the same last token (TOCTOU).  Early
    aborts that never reach the model call ``refund`` their token so a
    stream of bad files doesn't eat a visitor's quota.
    """

    def __init__(self) -> None:
        self._buckets: dict[str, Bucket] = {}
        self._lock = threading.Lock()

    def reserve(self, ip: str) -> tuple[bool, int]:
        """(reserved, retry_after_seconds) — decrements on success."""
        with self._lock:
            now = time.time()
            b = self._buckets.setdefault(ip, Bucket())
            b.tokens = min(BURST, b.tokens + (now - b.updated) * UPLOADS_PER_HOUR / 3600)
            b.updated = now
            if len(self._buckets) > 10_000:  # memory guard
                self._buckets = {k: v for k, v in self._buckets.items() if v.tokens < BURST}
            if b.tokens >= 1:
                b.tokens -= 1
                return True, 0
            deficit = 1 - b.tokens
            return False, int(deficit * 3600 / UPLOADS_PER_HOUR) + 1

    def refund(self, ip: str) -> None:
        with self._lock:
            b = self._buckets.get(ip)
            if b is not None:
                b.tokens = min(BURST, b.tokens + 1)


class Budget:
    """Daily model-call budget with the same atomic reserve/refund shape."""

    def __init__(self) -> None:
        self._day = ""
        self._spent = 0
        self._lock = threading.Lock()

    def _roll(self) -> None:
        day = time.strftime("%Y-%m-%d")
        if day != self._day:
            self._day, self._spent = day, 0

    @property
    def remaining(self) -> int:
        with self._lock:
            self._roll()
            return max(0, DAILY_MODEL_BUDGET - self._spent)

    def reserve(self) -> bool:
        with self._lock:
            self._roll()
            if self._spent < DAILY_MODEL_BUDGET:
                self._spent += 1
                return True
            return False

    def refund(self) -> None:
        with self._lock:
            self._roll()
            self._spent = max(0, self._spent - 1)


LIMITER = RateLimiter()
BUDGET = Budget()
