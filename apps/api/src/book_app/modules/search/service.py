"""Search use case (spec §9.6): rank matches, then enrich each result with
its own user state — "search keeps prior user states visible," unlike the
eligibility-filtered recommendation surfaces (spec §5.5). Read-only, no
transaction to own.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from book_app.modules.books.schemas import BookUserState
from book_app.modules.interactions import repository as interactions_repository
from book_app.modules.interactions.rating_scale import internal_to_public
from book_app.modules.search import repository as search_repository
from book_app.modules.search.repository import SearchResultRow
from book_app.modules.search.schemas import SearchResultItem
from book_app.modules.shelves import repository as shelves_repository
from book_app.shared.pagination import decode_cursor, encode_cursor

DEFAULT_LIMIT = 20


def _to_item(row: SearchResultRow, user_state: BookUserState) -> SearchResultItem:
    return SearchResultItem(
        book_id=row.book_id,
        work_id=row.work_id,
        title=row.title,
        primary_author_name=row.primary_author_name,
        cover_object_key=row.cover_object_key,
        user_state=user_state,
    )


def search_books(
    session: Session,
    *,
    user_id: UUID,
    query: str,
    limit: int = DEFAULT_LIMIT,
    cursor_str: str | None,
) -> tuple[list[SearchResultItem], str | None]:
    cursor = decode_cursor(cursor_str) if cursor_str else None

    # One extra row to know whether a next page exists, without a COUNT.
    rows = search_repository.search_books(session, query=query, limit=limit + 1, cursor=cursor)
    page_rows = rows[:limit]

    book_ids = [row.book_id for row in page_rows]
    states = interactions_repository.get_states_for_books(
        session, user_id=user_id, book_ids=book_ids
    )
    shelf_ids_by_book = shelves_repository.get_shelf_ids_for_books(
        session, user_id=user_id, book_ids=book_ids
    )

    items: list[SearchResultItem] = []
    for row in page_rows:
        state = states.get(row.book_id)
        user_state = BookUserState(
            rating=internal_to_public(state.rating_value) if state and state.rating_value else None,
            not_interested=state.not_interested if state else False,
            shelf_ids=shelf_ids_by_book.get(row.book_id, []),
        )
        items.append(_to_item(row, user_state))

    next_cursor: str | None = None
    if len(rows) > limit and page_rows:
        next_cursor = encode_cursor(search_repository.cursor_value_for_row(page_rows[-1]))

    return items, next_cursor
