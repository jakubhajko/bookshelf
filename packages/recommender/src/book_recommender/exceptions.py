"""Typed exceptions for this package (spec §10.1's fourth required file).

Deliberately plain ``Exception`` subclasses — no HTTP status codes or
FastAPI concerns belong here (spec §10.1: no FastAPI/ORM imports). The
application maps these to the spec §9.8 error envelope at its own boundary.
"""

from __future__ import annotations


class RecommenderError(Exception):
    """Base class for every exception this package raises."""


class EngineError(RecommenderError):
    """An engine failed to produce a result."""


class EngineTimeoutError(EngineError):
    """An engine did not respond within its allotted budget."""


class ProviderError(RecommenderError):
    """A provider failed to produce a batch after exhausting its own
    fallback chain (spec §10.10's terminal failure, before the API turns it
    into a 503)."""


class IncompatibleArtifactError(RecommenderError):
    """A loaded artifact doesn't match what its own manifest claims (spec
    §10.13: "reject incompatible mappings"), or is missing/unreadable."""
