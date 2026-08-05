"""Opaque cursor encoding: base64(JSON) of the last-seen sort key + tiebreaker.

Each repository that paginates decides what goes in the payload dict (e.g.
``{"rating": 8, "book_id": 4213}``) and how to turn it back into a keyset
WHERE clause — this module only owns making that payload opaque and
tamper-obvious to the client, not the query logic itself (the sort keys
differ too much between use cases for one generic query builder to be
worth it yet).
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from fastapi import status

from book_app.core.exceptions import AppError


class InvalidCursorError(AppError):
    code = "INVALID_CURSOR"
    status_code = status.HTTP_400_BAD_REQUEST
    message = "This page cursor is invalid or has expired."


def encode_cursor(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: str) -> dict[str, Any]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        decoded = json.loads(raw)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise InvalidCursorError() from exc
    if not isinstance(decoded, dict):
        raise InvalidCursorError()
    return decoded
