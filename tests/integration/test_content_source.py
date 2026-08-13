"""Content text/tag preparation against real PostgreSQL (rec-spec §11.2).

No encoder here: these cover the half of the content pipeline that decides
*what the model reads*, which is where the tag rules and the deterministic
template actually apply. No torch, no GPU, no model download — so they run
in the ordinary integration suite.
"""

from __future__ import annotations

from book_app.modules.recommendations.content_source import read_content_rows
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker


def _insert_book(
    engine: Engine,
    *,
    work_id: str,
    title: str,
    author: str | None = None,
    description: str | None = None,
    genre: str | None = None,
    status: str = "ACTIVE",
) -> int:
    with engine.begin() as conn:
        return int(
            conn.execute(
                text(
                    "INSERT INTO books "
                    "(work_id, title, primary_author_name, description, top_genre, "
                    "catalog_status) VALUES "
                    "(:work_id, :title, :author, :description, :genre, :status) RETURNING id"
                ),
                {
                    "work_id": work_id,
                    "title": title,
                    "author": author,
                    "description": description,
                    "genre": genre,
                    "status": status,
                },
            ).scalar_one()
        )


def _tag_book(engine: Engine, book_id: int, tags: list[tuple[str, int]]) -> None:
    """``tags`` are ``(name, source_count)`` — support decides ordering."""
    with engine.begin() as conn:
        for position, (name, source_count) in enumerate(tags):
            tag_id = conn.execute(
                text(
                    "INSERT INTO catalog_shelf_tags (name, normalized_name) "
                    "VALUES (:name, :name) "
                    "ON CONFLICT (normalized_name) DO UPDATE SET name = EXCLUDED.name "
                    "RETURNING id"
                ),
                {"name": name},
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO book_catalog_shelf_tags "
                    "(book_id, tag_id, source_count, position) "
                    "VALUES (:book_id, :tag_id, :source_count, :position)"
                ),
                {
                    "book_id": book_id,
                    "tag_id": tag_id,
                    "source_count": source_count,
                    "position": position,
                },
            )


def test_text_is_assembled_from_catalog_fields(
    test_session_factory: sessionmaker[Session], test_engine: Engine
) -> None:
    book_id = _insert_book(
        test_engine,
        work_id="w1",
        title="Dune",
        author="Frank Herbert",
        description="Paul Atreides comes to Arrakis.",
        genre="science fiction",
    )
    _tag_book(test_engine, book_id, [("desert", 900), ("politics", 400)])

    with test_session_factory() as session:
        rows, report = read_content_rows(session)

    assert len(rows) == 1
    text_value = rows[0].text.text
    assert "Title: Dune" in text_value
    assert "Author: Frank Herbert" in text_value
    assert "Themes: desert, politics" in text_value
    assert text_value.endswith("Paul Atreides comes to Arrakis.")
    assert report.with_description == 1
    assert report.with_tags == 1


def test_bookkeeping_tags_are_dropped_and_counted(
    test_session_factory: sessionmaker[Session], test_engine: Engine
) -> None:
    """The real catalog's tag list is mostly filing systems; this is the rule
    running against actual rows rather than string fixtures."""
    book_id = _insert_book(test_engine, work_id="w1", title="Dune")
    _tag_book(
        test_engine,
        book_id,
        [
            ("to-read", 5000),
            ("kindle-books", 4000),
            ("desert", 300),
            ("read-in-2011", 200),
        ],
    )

    with test_session_factory() as session:
        rows, report = read_content_rows(session)

    assert rows[0].tags == ("desert",)
    assert report.raw_tag_links == 4
    assert report.kept_tag_links == 1
    assert report.tag_rejections["bookkeeping-phrase"] == 1  # to-read
    assert report.tag_rejections["bookkeeping-token"] == 1  # kindle-books
    assert report.tag_rejections["reading-log-year"] == 1


def test_tags_are_ordered_by_reader_support(
    test_session_factory: sessionmaker[Session], test_engine: Engine
) -> None:
    """rec-spec §11.2 asks for "meaningful high-support thematic tags", and
    the per-book cap keeps whatever comes first."""
    book_id = _insert_book(test_engine, work_id="w1", title="Dune")
    _tag_book(
        test_engine, book_id, [("obscure", 3), ("popular", 5000), ("middling", 100)]
    )

    with test_session_factory() as session:
        rows, _ = read_content_rows(session)

    assert rows[0].tags == ("popular", "middling", "obscure")


def test_inactive_books_are_excluded(
    test_session_factory: sessionmaker[Session], test_engine: Engine
) -> None:
    _insert_book(test_engine, work_id="w1", title="Live")
    _insert_book(test_engine, work_id="w2", title="Hidden", status="HIDDEN")

    with test_session_factory() as session:
        rows, report = read_content_rows(session)

    assert [row.title for row in rows] == ["Live"]
    assert report.books == 1


def test_rows_are_in_catalog_item_order(
    test_session_factory: sessionmaker[Session], test_engine: Engine
) -> None:
    """Embedding row *i* must be ``model_item_index`` *i* in every other
    artifact family (ADR-0014)."""
    ids = [
        _insert_book(test_engine, work_id=f"w{index}", title=f"Book {index}")
        for index in range(5)
    ]

    with test_session_factory() as session:
        rows, _ = read_content_rows(session)

    assert [row.book_id for row in rows] == sorted(ids)


def test_a_book_with_no_description_still_produces_text(
    test_session_factory: sessionmaker[Session], test_engine: Engine
) -> None:
    _insert_book(test_engine, work_id="w1", title="Untitled Work")

    with test_session_factory() as session:
        rows, report = read_content_rows(session)

    assert rows[0].text.text == "Title: Untitled Work"
    assert report.with_description == 0


def test_limit_bounds_the_read(
    test_session_factory: sessionmaker[Session], test_engine: Engine
) -> None:
    for index in range(10):
        _insert_book(test_engine, work_id=f"w{index}", title=f"Book {index}")

    with test_session_factory() as session:
        rows, _ = read_content_rows(session, limit=3)

    assert len(rows) == 3


def test_the_text_is_deterministic_across_reads(
    test_session_factory: sessionmaker[Session], test_engine: Engine
) -> None:
    book_id = _insert_book(
        test_engine, work_id="w1", title="Dune", description="A story.", genre="sci-fi"
    )
    _tag_book(test_engine, book_id, [("desert", 900), ("politics", 400)])

    with test_session_factory() as session:
        first, _ = read_content_rows(session)
    with test_session_factory() as session:
        second, _ = read_content_rows(session)

    assert [row.text.text for row in first] == [row.text.text for row in second]
