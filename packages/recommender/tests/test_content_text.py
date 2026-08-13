"""Tag cleaning and deterministic book text (rec-spec §11.2).

These two functions decide what the encoder sees, so a mistake here is not a
crash — it is 92,524 subtly wrong vectors that take 88 minutes to rebuild.
"""

from __future__ import annotations

import pytest

from book_recommender.content import (
    TAG_CLEANING_VERSION,
    TEXT_TEMPLATE_VERSION,
    build_book_text,
    clean_tags,
    is_useful_tag,
    rejection_reason,
    summarize_rejections,
)
from book_recommender.content.text_builder import MAX_DESCRIPTION_CHARS

# --- Tag cleaning -----------------------------------------------------------


@pytest.mark.parametrize(
    "tag",
    [
        "science-fiction",
        "historical-fiction",
        "magical-realism",
        "russian-literature",
        "20th-century",
        "world-war-ii",
        "coming-of-age",
        "true-crime",
        "graphic-novels",
        "architecture",
    ],
)
def test_thematic_tags_survive(tag: str) -> None:
    assert is_useful_tag(tag), rejection_reason(tag)


@pytest.mark.parametrize(
    "tag",
    [
        "to-read",
        "currently-reading",
        "own-to-read",
        "books-i-have",
        "personal-library",
        "kindle-books",
        "audio-books",
        "shelfari-wishlist",
        "my-bookshelf",
        "read-in-2011",
        "2012-reads",
        "1001-books-to-read-before-you-die",
        "favorites",
        "all-time-favorites",
        "want-to-read",
        "library-book",
        "borrowed",
        "dnf",
        "default",
        "in-my-library",
    ],
)
def test_bookkeeping_tags_are_rejected(tag: str) -> None:
    assert not is_useful_tag(tag)
    assert rejection_reason(tag) is not None


def test_matching_is_on_whole_tokens_not_substrings() -> None:
    """``own`` must reject ``own-to-read`` without touching ``downtown``, and
    ``read`` must not take ``spreadsheets`` with it."""
    assert not is_useful_tag("own-to-read")
    assert is_useful_tag("downtown-noir")
    assert is_useful_tag("spreadsheets")
    assert is_useful_tag("readable-science")  # 'readable' is not 'read'


def test_a_year_marks_a_reading_log_but_a_century_does_not() -> None:
    assert rejection_reason("read-in-2011") == "reading-log-year"
    assert rejection_reason("2012") == "reading-log-year"
    assert is_useful_tag("20th-century")
    assert is_useful_tag("19th-century-literature")


def test_clean_tags_deduplicates_on_the_normalized_form() -> None:
    cleaned = clean_tags(["Science Fiction", "science-fiction", "sci-fi"])

    # The first two normalize to the same token sequence; sci-fi does not.
    assert cleaned == ("science fiction", "sci-fi")


def test_clean_tags_preserves_input_order_and_caps() -> None:
    """The builder passes tags sorted by support, so the cap must keep the
    best-attested ones rather than an arbitrary slice."""
    tags = [f"theme-{index}" for index in range(30)]

    cleaned = clean_tags(tags, max_tags=5)

    assert cleaned == ("theme-0", "theme-1", "theme-2", "theme-3", "theme-4")


def test_clean_tags_drops_bookkeeping_without_consuming_cap_slots() -> None:
    cleaned = clean_tags(["to-read", "fantasy", "owned", "epic-fantasy"], max_tags=2)

    assert cleaned == ("fantasy", "epic-fantasy")


def test_short_and_overlong_tags_are_rejected() -> None:
    assert rejection_reason("sf") == "too-short"
    assert rejection_reason("x" * 41) == "too-long"


def test_summarize_rejections_groups_by_reason() -> None:
    summary = summarize_rejections(["to-read", "owned", "read-in-2011", "fantasy"])

    assert summary["bookkeeping-token"] == 1  # owned
    assert summary["bookkeeping-phrase"] == 1  # to-read
    assert summary["reading-log-year"] == 1
    assert "fantasy" not in summary


def test_cleaning_version_is_declared() -> None:
    assert TAG_CLEANING_VERSION


# --- Book text --------------------------------------------------------------


def test_text_follows_the_documented_template() -> None:
    result = build_book_text(
        title="Dune",
        author="Frank Herbert",
        genres=["science fiction"],
        tags=["desert", "politics"],
        description="Paul Atreides comes to Arrakis.",
    )

    assert result.text == (
        "Title: Dune\n"
        "Author: Frank Herbert\n"
        "Genres: science fiction\n"
        "Themes: desert, politics\n"
        "Description:\n"
        "Paul Atreides comes to Arrakis."
    )
    assert result.used_description
    assert result.tag_count == 2


def test_absent_fields_are_omitted_rather_than_left_dangling() -> None:
    """~2,300 catalog books have no author. A bare ``Author:`` line would be
    noise the encoder has to interpret."""
    result = build_book_text(title="Untitled Work")

    assert result.text == "Title: Untitled Work"
    assert "Author:" not in result.text
    assert not result.used_description


def test_the_builder_is_deterministic() -> None:
    kwargs = {
        "title": "Dune",
        "author": "Frank Herbert",
        "genres": ["science fiction"],
        "tags": ["desert"],
        "description": "Paul Atreides comes to Arrakis.",
    }

    assert build_book_text(**kwargs).text == build_book_text(**kwargs).text  # type: ignore[arg-type]


def test_whitespace_is_normalized_so_formatting_cannot_change_a_vector() -> None:
    messy = build_book_text(title="X", description="A  b\n\n\tc   d")
    clean = build_book_text(title="X", description="A b c d")

    assert messy.text == clean.text


def test_long_descriptions_are_clipped_on_a_word_boundary() -> None:
    description = "word " * 2000

    result = build_book_text(title="X", description=description)

    assert len(result.text) < MAX_DESCRIPTION_CHARS + 200
    assert result.text.endswith("…")


def test_description_comes_last_so_truncation_keeps_title_and_author() -> None:
    """Encoder truncation removes the tail. The fields most likely to be
    discriminative must be guaranteed to survive it."""
    result = build_book_text(title="Dune", author="Frank Herbert", description="x" * 5000)

    lines = result.text.split("\n")
    assert lines[0].startswith("Title:")
    assert lines[1].startswith("Author:")
    assert lines[-2] == "Description:"


def test_ratings_and_identifiers_never_reach_the_text() -> None:
    """rec-spec §11.2's "Do not embed" list — popularity and ids are ranking
    features, and embedding them would cluster books by how well they sold."""
    result = build_book_text(
        title="Dune",
        author="Frank Herbert",
        genres=["science fiction"],
        tags=["desert"],
        description="A story.",
    )

    for forbidden in ("rating", "isbn", "pages", "book_id", "work_id", "4.2"):
        assert forbidden not in result.text.lower()


def test_genres_are_capped() -> None:
    result = build_book_text(title="X", genres=[f"g{index}" for index in range(20)])

    assert result.genre_count == 5


def test_template_version_is_declared() -> None:
    assert TEXT_TEMPLATE_VERSION
