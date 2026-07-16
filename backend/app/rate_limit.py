"""Lightweight in-process rate limiter for brute-force protection.

This is a deliberately simple sliding-window limiter that lives in process
memory. It is sufficient for a single-instance portal deployment to blunt
credential-stuffing / brute-force attacks against the auth endpoints. It is
NOT a distributed limiter; if the API is ever scaled horizontally this should
be backed by Redis instead.

Usage:
    limiter = RateLimiter(max_attempts=5, window_seconds=300)
    if not limiter.allow(key):
        raise HTTPException(429, ...)
    # on a *failed* auth attempt:
    limiter.register_failure(key)
    # on success, clear the counter:
    limiter.reset(key)
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, max_attempts: int = 5, window_seconds: int = 300) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> None:
        bucket = self._hits[key]
        cutoff = now - self.window_seconds
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if not bucket:
            self._hits.pop(key, None)

    def allow(self, key: str) -> bool:
        """Return True if another attempt is currently permitted for *key*."""
        now = time.monotonic()
        with self._lock:
            self._prune(key, now)
            return len(self._hits.get(key, ())) < self.max_attempts

    def register_failure(self, key: str) -> None:
        """Record a failed attempt against *key*."""
        now = time.monotonic()
        with self._lock:
            self._prune(key, now)
            self._hits[key].append(now)

    def retry_after(self, key: str) -> int:
        """Seconds until the oldest attempt in the window expires."""
        now = time.monotonic()
        with self._lock:
            bucket = self._hits.get(key)
            if not bucket:
                return 0
            return max(1, int(self.window_seconds - (now - bucket[0])))

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def reset_all(self) -> None:
        with self._lock:
            self._hits.clear()


# Targeted limiter: 8 failed attempts per 5 minutes for one IP+username pair.
login_limiter = RateLimiter(max_attempts=8, window_seconds=300)
# Broad IP limiter: prevents username spraying and spoofed-IP bypasses.
login_ip_limiter = RateLimiter(max_attempts=40, window_seconds=300)
