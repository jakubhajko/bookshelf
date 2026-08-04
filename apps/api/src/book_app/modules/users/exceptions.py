"""Typed errors for the users module, mapped to the shared spec §9.8 envelope."""

from __future__ import annotations

from fastapi import status

from book_app.core.exceptions import AppError


class InvalidUsernameError(AppError):
    code = "USERNAME_INVALID"
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    message = "That username is not allowed."


class UsernameReservedError(AppError):
    code = "USERNAME_RESERVED"
    status_code = status.HTTP_409_CONFLICT
    message = "That username is reserved."


class UsernameTakenError(AppError):
    code = "USERNAME_TAKEN"
    status_code = status.HTTP_409_CONFLICT
    message = "That username is already taken."
