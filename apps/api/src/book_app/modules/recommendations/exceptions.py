"""Typed errors for the recommendations module, mapped to the shared spec
§9.8 envelope.

A malformed cursor (bad base64/JSON) raises
``shared.pagination.InvalidCursorError`` directly from the shared codec —
reused as-is, same as ``/me/ratings``/``/shelves/{id}/books`` (spec §4's
``shared/pagination/``). ``RecommendationCursorInvalidError`` here is for a
well-formed cursor whose *referenced batch* is gone: expired, never existed,
or belongs to someone else. Those three read identically (spec §6.6's
existence-hiding principle, same as ``SHELF_NOT_FOUND``) rather than leaking
which case applies.
"""

from __future__ import annotations

from fastapi import status

from book_app.core.exceptions import AppError


class RecommendationCursorInvalidError(AppError):
    code = "RECOMMENDATION_CURSOR_INVALID"
    status_code = status.HTTP_400_BAD_REQUEST
    message = "This recommendation page cursor no longer refers to a live batch."


class RecommendationUnavailableError(AppError):
    code = "RECOMMENDATION_UNAVAILABLE"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "Recommendations are temporarily unavailable."
