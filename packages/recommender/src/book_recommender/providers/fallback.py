"""Fallback provider (spec §10.10): try a configured primary provider; on
failure, timeout, or an invalid result, retry via a popularity fallback
provider; if that also fails, raise :class:`ProviderError` so the caller can
return 503.

Doesn't log anything itself — spec §10.10's "log provider, model version,
request ID, latency, and fallback" is an application-level concern (this
package has no logging configuration of its own, and request IDs/latency
timing naturally belong to the caller). The caller reads ``fallback_used``
and ``diagnostics`` off the returned batch to do that logging.
"""

from __future__ import annotations

from asyncio import timeout as asyncio_timeout

from book_recommender.contracts.provider import (
    RecommendationBatch,
    RecommendationProvider,
    RecommendationRequest,
)
from book_recommender.exceptions import ProviderError


def _is_valid(batch: RecommendationBatch, request: RecommendationRequest) -> bool:
    """Provider-layer sanity check, ahead of the application's own
    defensive validation (spec §10.8) — no duplicates, nothing the request
    explicitly excluded."""
    excluded = request.hard_exclusions | request.session_exclusions
    book_ids = [c.book_id for c in batch.candidates]
    if len(book_ids) != len(set(book_ids)):
        return False
    return not any(book_id in excluded for book_id in book_ids)


class FallbackProvider:
    def __init__(
        self,
        primary: RecommendationProvider,
        fallback: RecommendationProvider,
        *,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._timeout_seconds = timeout_seconds

    async def recommend(self, request: RecommendationRequest) -> RecommendationBatch:
        try:
            async with asyncio_timeout(self._timeout_seconds):
                batch = await self._primary.recommend(request)
            if _is_valid(batch, request):
                return batch
            primary_error = "primary provider returned an invalid batch"
        except TimeoutError:
            primary_error = "primary provider timed out"
        except Exception as exc:  # any primary failure triggers fallback, deliberately broad
            primary_error = f"primary provider failed: {exc}"

        try:
            async with asyncio_timeout(self._timeout_seconds):
                batch = await self._fallback.recommend(request)
        except Exception as exc:
            raise ProviderError(
                f"both primary and fallback providers failed; "
                f"primary: {primary_error}; fallback: {exc}"
            ) from exc

        if not _is_valid(batch, request):
            raise ProviderError("fallback provider also returned an invalid batch")

        return batch.model_copy(
            update={
                "fallback_used": True,
                "diagnostics": {**batch.diagnostics, "primary_error": primary_error},
            }
        )
