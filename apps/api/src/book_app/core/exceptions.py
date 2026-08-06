"""Application exceptions and the shared error envelope (APP_SPECIFICATION.md §9.8).

``AppError`` is the base every module's ``exceptions.py`` should subclass
from Phase 2 onward (e.g. ``ShelfNotFoundError(AppError)``) so every endpoint
in the application returns the same JSON shape. Nothing here ever includes a
stack trace or raw database error in the response body (spec §14/§20).
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from book_app.shared.schemas.error import ErrorBody, ErrorEnvelope

logger = structlog.get_logger("book_app.errors")

_STATUS_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
}


class AppError(Exception):
    """Base class for typed application errors mapped to the §9.8 envelope."""

    code: str = "INTERNAL_ERROR"
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    message: str = "An unexpected error occurred."

    def __init__(
        self, message: str | None = None, *, details: dict[str, object] | None = None
    ) -> None:
        super().__init__(message or self.message)
        if message:
            self.message = message
        self.details = details or {}


class ServiceUnavailableError(AppError):
    code = "SERVICE_UNAVAILABLE"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "The service is temporarily unavailable."


class CoverNotFoundError(AppError):
    code = "COVER_NOT_FOUND"
    status_code = status.HTTP_404_NOT_FOUND
    message = "The requested cover image does not exist."


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


def _envelope(
    code: str, message: str, details: dict[str, object], request_id: str
) -> dict[str, object]:
    return ErrorEnvelope(
        error=ErrorBody(code=code, message=message, details=details, request_id=request_id)
    ).model_dump(mode="json")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.code, exc.message, exc.details, _request_id(request)),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=_envelope(
                "VALIDATION_ERROR",
                "The request could not be validated.",
                {"errors": exc.errors()},
                _request_id(request),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(
                _STATUS_CODES.get(exc.status_code, "HTTP_ERROR"),
                str(exc.detail),
                {},
                _request_id(request),
            ),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", path=request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope(
                "INTERNAL_ERROR", "An unexpected error occurred.", {}, _request_id(request)
            ),
        )
