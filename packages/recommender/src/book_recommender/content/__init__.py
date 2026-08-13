"""Deterministic content preparation for the embedding artifact (rec-spec §11.2).

Pure and dependency-free: tag cleaning and book-text construction are the two
things that decide what the encoder actually sees, so they live here — beside
the loader — rather than in the offline builder, and are versioned so an
artifact can say which rules produced it.
"""

from __future__ import annotations

from book_recommender.content.tags import (
    MAX_TAGS_PER_BOOK,
    TAG_CLEANING_VERSION,
    clean_tags,
    is_useful_tag,
    rejection_reason,
    summarize_rejections,
)
from book_recommender.content.text_builder import (
    TEXT_TEMPLATE_VERSION,
    BookText,
    build_book_text,
)

__all__ = [
    "MAX_TAGS_PER_BOOK",
    "TAG_CLEANING_VERSION",
    "TEXT_TEMPLATE_VERSION",
    "BookText",
    "build_book_text",
    "clean_tags",
    "is_useful_tag",
    "rejection_reason",
    "summarize_rejections",
]
