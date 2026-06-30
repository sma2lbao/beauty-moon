"""In-process fixed-window rate limiter.

Per-process state only; not shared across replicas. Multi-instance
correctness (Redis-backed) is a deferred M8/scale follow-up.
"""
import time
from collections.abc import Callable

_WINDOW_SECONDS = 60.0


class RateLimiter:
    """Fixed 60-second window counter keyed by an arbitrary string."""

    def __init__(self, now_fn: Callable[[], float] = time.monotonic) -> None:
        self._now = now_fn
        # key -> (window_start, count)
        self._windows: dict[str, tuple[float, int]] = {}

    def check(self, key: str, limit_per_minute: int) -> bool:
        """Record a hit for key; return True if within limit, else False."""
        now = self._now()
        window_start, count = self._windows.get(key, (now, 0))
        if now - window_start >= _WINDOW_SECONDS:
            window_start, count = now, 0
        count += 1
        self._windows[key] = (window_start, count)
        return count <= limit_per_minute
