"""Pluggable rate-limit boundary (spec §14: "Provide a pluggable auth
rate-limit boundary. Per-process limiting is acceptable locally; document
AWS WAF/shared production limiting.").

The in-process fixed-window limiter below is what Phase 3 wires to the
login endpoint. It only limits attempts on *this* process — correct for a
single local/Compose instance, not for a horizontally-scaled deployment
(multiple ECS Fargate tasks wouldn't share counters). On AWS, put this
behind (or replace it with) AWS WAF rate-based rules or a shared store
(e.g. an ElastiCache-backed limiter) in front of/alongside the ALB — that's
an infrastructure decision for whenever real AWS deployment happens (spec
§2/§17: not provisioned in version one), not a code change here: anything
satisfying the ``RateLimiter`` protocol drops in without touching callers.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from typing import Protocol


class RateLimiter(Protocol):
    def check(self, key: str) -> bool:
        """Return True if another attempt under ``key`` is currently allowed."""
        ...


class InMemoryFixedWindowRateLimiter:
    """Per-process, fixed-window limiter. Not shared across multiple workers/instances."""

    def __init__(
        self,
        max_attempts: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._clock = clock
        self._attempts: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> bool:
        now = self._clock()
        window_start = now - self._window_seconds

        attempts = [t for t in self._attempts[key] if t > window_start]
        if len(attempts) >= self._max_attempts:
            self._attempts[key] = attempts
            return False

        attempts.append(now)
        self._attempts[key] = attempts
        return True
