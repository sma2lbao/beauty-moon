"""Tests for the in-process rate limiter."""
from app.security.rate_limiter import RateLimiter


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_allows_under_limit():
    limiter = RateLimiter(now_fn=FakeClock())
    assert all(limiter.check("user-a", 3) for _ in range(3))


def test_blocks_over_limit():
    limiter = RateLimiter(now_fn=FakeClock())
    for _ in range(3):
        limiter.check("user-a", 3)
    assert limiter.check("user-a", 3) is False


def test_window_resets_after_60s():
    clock = FakeClock()
    limiter = RateLimiter(now_fn=clock)
    for _ in range(3):
        limiter.check("user-a", 3)
    assert limiter.check("user-a", 3) is False
    clock.t += 61
    assert limiter.check("user-a", 3) is True


def test_keys_are_independent():
    limiter = RateLimiter(now_fn=FakeClock())
    for _ in range(3):
        limiter.check("user-a", 3)
    assert limiter.check("user-b", 3) is True


def test_stale_windows_are_evicted():
    clock = FakeClock()
    limiter = RateLimiter(now_fn=clock)
    limiter.check("user-a", 3)
    assert "user-a" in limiter._windows
    # Advance past the window and touch a different key; stale entry is dropped.
    clock.t += 61
    limiter.check("user-b", 3)
    assert "user-a" not in limiter._windows
    assert "user-b" in limiter._windows
