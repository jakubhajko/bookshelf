"""Typed errors for the auth module, mapped to the shared spec §9.8 envelope.

Deliberately vague between "wrong username" and "wrong password"
(``InvalidCredentialsError`` covers both) — a precise error would let an
attacker enumerate valid usernames.
"""

from __future__ import annotations

from fastapi import status

from book_app.core.exceptions import AppError


class InvalidCredentialsError(AppError):
    code = "INVALID_CREDENTIALS"
    status_code = status.HTTP_401_UNAUTHORIZED
    message = "Invalid username or password."


class AccountDisabledError(AppError):
    code = "ACCOUNT_DISABLED"
    status_code = status.HTTP_403_FORBIDDEN
    message = "This account is disabled."


class NotAuthenticatedError(AppError):
    code = "NOT_AUTHENTICATED"
    status_code = status.HTTP_401_UNAUTHORIZED
    message = "Authentication is required."


class SessionInvalidError(AppError):
    code = "SESSION_INVALID"
    status_code = status.HTTP_401_UNAUTHORIZED
    message = "This session is no longer valid."


class CsrfInvalidError(AppError):
    code = "CSRF_INVALID"
    status_code = status.HTTP_403_FORBIDDEN
    message = "CSRF validation failed."


class InvalidPasswordError(AppError):
    code = "PASSWORD_INVALID"
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    message = "That password is not allowed."


class PasswordMismatchError(AppError):
    code = "PASSWORD_MISMATCH"
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    message = "Password and confirmation do not match."


class IncorrectPasswordError(AppError):
    code = "PASSWORD_INCORRECT"
    status_code = status.HTTP_401_UNAUTHORIZED
    message = "Current password is incorrect."


class RateLimitedError(AppError):
    code = "RATE_LIMITED"
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    message = "Too many attempts. Try again later."
