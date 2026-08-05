"""Deterministic, exclusion-respecting mock engine (spec §10.11)."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from random import Random

from book_recommender.contracts.context import SimilarBooksContext
from book_recommender.contracts.engine import (
    EngineCandidate,
    RecommendationEngineRequest,
    RecommendationEngineResult,
)
from book_recommender.contracts.reasons import ReasonCode
from book_recommender.exceptions import EngineError

MODEL_NAME = "mock"
MODEL_VERSION = "1"

_SURFACE_REASONS: dict[str, tuple[ReasonCode, ...]] = {
    "home": (
        ReasonCode.POPULAR_WITH_READERS,
        ReasonCode.EXPLORATION,
        ReasonCode.BASED_ON_HIGH_RATINGS,
    ),
    "shelf": (ReasonCode.SIMILAR_TO_SHELF, ReasonCode.EXPLORATION),
    "similar": (ReasonCode.SIMILAR_TO_CURRENT_BOOK,),
    "search": (ReasonCode.SEMANTIC_QUERY_MATCH,),
}


def _seed_for(request: RecommendationEngineRequest) -> int:
    """Same request -> same output (spec §10.11: "deterministic in tests").
    Built from ``hashlib`` rather than the builtin ``hash()`` — ``hash()`` on
    strings is randomized per-process by default, which would make this seed
    (and therefore the whole engine's output) different on every test run."""
    raw = f"{request.request_id}:{request.user_context.user_id}:{request.surface_context.surface}"
    digest = hashlib.sha256(raw.encode()).digest()
    return int.from_bytes(digest[:8], "big")


class MockRecommendationEngine:
    """Draws from a fixed candidate pool the caller supplies at construction
    time — this package has no database access (spec §10.1), so it can't
    discover "active books" on its own. The application is expected to
    supply real, currently-active book_ids so results validate cleanly
    against the real catalog end to end (spec §10.8).
    """

    def __init__(
        self,
        candidate_pool: Sequence[int],
        *,
        failure_rate: float = 0.0,
        latency_seconds: float = 0.0,
    ) -> None:
        self._pool = tuple(candidate_pool)
        self._failure_rate = failure_rate
        self._latency_seconds = latency_seconds

    def recommend(self, request: RecommendationEngineRequest) -> RecommendationEngineResult:
        if self._latency_seconds:
            time.sleep(self._latency_seconds)

        rng = Random(_seed_for(request))
        if self._failure_rate and rng.random() < self._failure_rate:
            raise EngineError("mock engine simulated failure")

        surface = request.surface_context
        excluded = set(request.hard_exclusions) | set(request.session_exclusions)
        if isinstance(surface, SimilarBooksContext):
            excluded.add(surface.source_book_id)

        # Shuffle rather than slice in pool order (spec §10.11: "not merely
        # return first rows") while staying reproducible for the same seed.
        eligible = [book_id for book_id in self._pool if book_id not in excluded]
        rng.shuffle(eligible)
        chosen = eligible[: request.requested_count]

        reasons = _SURFACE_REASONS[surface.surface]
        candidates = tuple(
            EngineCandidate(
                book_id=book_id,
                score=round(1.0 - (position / max(len(chosen), 1)), 4),
                candidate_sources=("mock",),
                reason_code=reasons[position % len(reasons)],
                diagnostics={"pool_size": len(self._pool)},
            )
            for position, book_id in enumerate(chosen)
        )
        return RecommendationEngineResult(
            model_name=MODEL_NAME,
            model_version=MODEL_VERSION,
            catalog_version=request.catalog_version,
            generated_at=datetime.now(UTC),
            candidates=candidates,
            diagnostics={"surface": surface.surface},
        )
