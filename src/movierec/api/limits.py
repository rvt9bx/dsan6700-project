"""Per-client rate limiting for expensive routes."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

# Forget clients whose buckets have refilled once there are this many, so memory stays bounded
MAX_TRACKED_CLIENTS = 10_000


@dataclass
class _Bucket:
    """One client's tokens, and when they were last counted."""

    tokens: float
    updated: float


class RateLimiter:
    """A token bucket per client: `burst` calls at once, refilled at `per_minute`.

    State is kept in this process's memory, so with two copies of the app each would
    allow the full rate; a shared store such as Redis would fix that.
    """

    def __init__(
        self,
        per_minute: float,
        burst: int,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.rate = per_minute / 60  # tokens per second
        self.burst = burst
        self.clock = clock
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def acquire(self, client: str) -> int:
        """Take one token for this client.

        Returns 0 if the call is allowed, otherwise how many whole seconds to wait
        before a token is available (the value for a Retry-After header).
        """
        now = self.clock()
        with self._lock:
            bucket = self._buckets.get(client)
            if bucket is None:
                if len(self._buckets) >= MAX_TRACKED_CLIENTS:
                    self._forget_full_buckets(now)
                bucket = self._buckets[client] = _Bucket(self.burst, now)
            else:
                bucket.tokens = self._refilled(bucket, now)
                bucket.updated = now

            if bucket.tokens >= 1:
                bucket.tokens -= 1
                return 0
            return max(1, math.ceil((1 - bucket.tokens) / self.rate))

    def reset(self) -> None:
        """Forget every client (used by tests)."""
        with self._lock:
            self._buckets.clear()

    def _refilled(self, bucket: _Bucket, now: float) -> float:
        """The bucket's tokens after refilling since it was last counted."""
        return min(self.burst, bucket.tokens + (now - bucket.updated) * self.rate)

    def _forget_full_buckets(self, now: float) -> None:
        """Drop clients that are back to a full bucket: they would start full anyway."""
        full = [
            client
            for client, bucket in self._buckets.items()
            if self._refilled(bucket, now) >= self.burst
        ]
        for client in full:
            del self._buckets[client]
