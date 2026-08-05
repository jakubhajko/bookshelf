"""Typed errors for the books module, mapped to the shared spec §9.8 envelope.

Imported by other modules (interactions, shelves) whenever they need to
verify a book_id exists — the books module owns what "the book doesn't
exist" means, the same way ``modules/users`` owns ``UsernameTakenError``.
"""

from __future__ import annotations

from fastapi import status

from book_app.core.exceptions import AppError


class BookNotFoundError(AppError):
    code = "BOOK_NOT_FOUND"
    status_code = status.HTTP_404_NOT_FOUND
    message = "The requested book does not exist."
