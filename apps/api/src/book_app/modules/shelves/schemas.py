"""Request/response schemas for shelves endpoints (spec §9.3). Never expose
ORM objects directly (spec §4.2).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ShelfCreateRequest(BaseModel):
    name: str
    description: str | None = None


class ShelfUpdateRequest(BaseModel):
    """Partial update (PATCH): only fields the client actually sent should
    change. Read via ``model_dump(exclude_unset=True)`` in api.py, not by
    checking for ``None`` here — ``None`` is a valid, meaningful value for
    ``description`` (clear it), distinct from "not provided"."""

    name: str | None = None
    description: str | None = None


class ShelfPublic(BaseModel):
    id: UUID
    name: str
    description: str | None
    book_count: int
    cover_object_keys: list[str]
    created_at: datetime
    updated_at: datetime


class ShelfBookItem(BaseModel):
    book_id: int
    work_id: str
    title: str
    primary_author_name: str | None
    cover_object_key: str | None
    added_at: datetime


class ShelfIdsResponse(BaseModel):
    shelf_ids: list[UUID]
