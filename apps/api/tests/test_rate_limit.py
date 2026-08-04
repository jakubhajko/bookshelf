"""Tests for the in-process rate limiter (spec §14: pluggable auth rate-limit boundary)."""

from __future__ import annotations

from book_app.shared.rate_limit import InMemoryFixedWindowRateLimiter


def test_allows_up_to_max_attempts() -> None:
    limiter = InMemoryFixedWindowRateLimiter(max_attempts=3, window_seconds=60)
    assert limiter.check("key") is True
    assert limiter.check("key") is True
    assert limiter.check("key") is True


def test_blocks_after_max_attempts() -> None:
    limiter = InMemoryFixedWindowRateLimiter(max_attempts=3, window_seconds=60)
    for _ in range(3):
        limiter.check("key")
    assert limiter.check("key") is False


def test_different_keys_are_independent() -> None:
    limiter = InMemoryFixedWindowRateLimiter(max_attempts=1, window_seconds=60)
    assert limiter.check("a") is True
    assert limiter.check("b") is True
    assert limiter.check("a") is False


def test_allows_again_after_window_elapses() -> None:
    now = [1000.0]
    limiter = InMemoryFixedWindowRateLimiter(
        max_attempts=1, window_seconds=10, clock=lambda: now[0]
    )
    assert limiter.check("key") is True
    assert limiter.check("key") is False
    now[0] += 11
    assert limiter.check("key") is True


def test_partial_window_expiry_only_frees_old_attempts() -> None:
    now = [0.0]
    limiter = InMemoryFixedWindowRateLimiter(
        max_attempts=2, window_seconds=10, clock=lambda: now[0]
    )
    assert limiter.check("key") is True  # t=0
    now[0] = 5
    assert limiter.check("key") is True  # t=5, both t=0 and t=5 now recorded
    now[0] = 9
    assert limiter.check("key") is False  # t=9: t=0 and t=5 both still within the last 10s
    now[0] = 11
    assert limiter.check("key") is True  # t=11: only t=5 remains in window, room for one more
