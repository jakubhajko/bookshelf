"""Public response shapes for users — never expose ORM objects directly (spec §4.2)."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
