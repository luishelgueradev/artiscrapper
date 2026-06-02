"""
GoogleRateLimiter — asyncio.Semaphore(1) + timestamp gate.
Pattern 1 GoogleRateLimiter section from 02-RESEARCH.md.
BROWSER-04: Serializes Google fetches, ensures >= GOOGLE_MIN_INTERVAL_S between fetches.
T-02-01-06: DoS mitigation — hard 60s floor between Google fetches.
"""
import asyncio
import time


class GoogleRateLimiter:
    """
    Serializes Google fetches: asyncio.Semaphore(1) + monotonic timestamp gate.
    acquire() is async: awaits the semaphore, checks elapsed time,
    sleeps the remainder if elapsed < min_interval_s, then updates _last_fetch.
    This ensures >= GOOGLE_MIN_INTERVAL_S between Google fetches.
    """

    def __init__(self, min_interval_s: float = 60.0) -> None:
        self._sem = asyncio.Semaphore(1)
        self._last_fetch: float = 0.0
        self._min_interval = min_interval_s

    async def acquire(self) -> None:
        async with self._sem:
            elapsed = time.monotonic() - self._last_fetch
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_fetch = time.monotonic()
