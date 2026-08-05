"""Typed errors for the interactions module, mapped to the shared spec §9.8 envelope."""

from __future__ import annotations

from fastapi import status

from book_app.core.exceptions import AppError


class InvalidRatingError(AppError):
    code = "RATING_INVALID"
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    message = "Rating must be a half-step value from 0.5 to 5.0."
