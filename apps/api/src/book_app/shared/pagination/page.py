"""Generic paginated-response envelope."""

from __future__ import annotations

from pydantic import BaseModel


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None
