"""Typed errors for the shelves module, mapped to the shared spec §9.8 envelope."""

from __future__ import annotations

from fastapi import status

from book_app.core.exceptions import AppError


class InvalidShelfNameError(AppError):
    code = "SHELF_NAME_INVALID"
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    message = "That shelf name is not allowed."


class ShelfNameTakenError(AppError):
    code = "SHELF_NAME_TAKEN"
    status_code = status.HTTP_409_CONFLICT
    message = "You already have a shelf with that name."


class ShelfNotFoundError(AppError):
    code = "SHELF_NOT_FOUND"
    status_code = status.HTTP_404_NOT_FOUND
    message = "The requested shelf does not exist."
