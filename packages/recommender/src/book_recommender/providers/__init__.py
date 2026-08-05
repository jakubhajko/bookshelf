"""Asynchronous ``RecommendationProvider`` implementations (spec §10.3)."""

from __future__ import annotations

from book_recommender.providers.fallback import FallbackProvider
from book_recommender.providers.in_process import InProcessProvider
from book_recommender.providers.remote import RemoteProvider

__all__ = ["FallbackProvider", "InProcessProvider", "RemoteProvider"]
