"""Remote-provider skeleton (spec §10.3: "remote-provider interface/skeleton").

Not implemented — no remote inference service exists yet. Exists so the
``RecommendationProvider`` protocol has a documented seam for one without
building real HTTP client/auth/retry logic prematurely (spec §2/§20: don't
implement the final funnel ahead of need).
"""

from __future__ import annotations

from book_recommender.contracts.provider import RecommendationBatch, RecommendationRequest
from book_recommender.exceptions import ProviderError

PROVIDER_NAME = "remote"


class RemoteProvider:
    """Conforms to :class:`~book_recommender.contracts.provider.RecommendationProvider`;
    every call raises until a real remote inference endpoint exists to call."""

    def __init__(self, endpoint_url: str) -> None:
        self._endpoint_url = endpoint_url

    async def recommend(self, request: RecommendationRequest) -> RecommendationBatch:
        raise ProviderError(
            "remote provider is a skeleton — no remote inference service is configured "
            f"(would have called {self._endpoint_url!r})"
        )
