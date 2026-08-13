"""Deterministic catalog shelf-tag cleaning (rec-spec §11.2).

Goodreads shelf names are user-authored, and most of the high-frequency ones
describe a reader's *filing system* rather than the book. The live catalog
has 173,787 distinct tags over 1,699,225 book links, and the top of that
list is a mixture: ``fiction`` (51,384 books) and ``historical-fiction``
sit next to ``to-read``, ``books-i-have``, ``kindle-books``,
``shelfari-wishlist`` and ``read-in-2011``.

Embedding the second group would be actively harmful — it would cluster
books by how people file them rather than by what they are about, and
"books I own on Kindle" is not an interest. rec-spec §11.2: "Filter obvious
bookkeeping/status/personal-library tags and cap the number per book. Keep
cleaning rules deterministic, testable and versioned."

**Token matching, not substring matching.** ``own`` must reject
``own-to-read`` without touching ``downtown``; ``read`` must reject
``to-read`` without touching ``spreadsheets``. Tags are split on the
separators Goodreads normalizes to, and a tag is rejected when any *whole
token* is a bookkeeping word.

**The rules are versioned.** ``TAG_CLEANING_VERSION`` is recorded in every
artifact built with them, so a change to this file is visible as an artifact
that is no longer comparable to its predecessor rather than as a silent
shift in what the embeddings mean.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

#: Bump when the rules below change the output for any realistic input.
TAG_CLEANING_VERSION = "tags-v1"

#: Whole tokens that mark a tag as personal bookkeeping rather than subject
#: matter. Grouped by what they are, because the groups get argued about
#: separately.
_STATUS_TOKENS = frozenset(
    {
        # reading status
        "read",
        "reads",
        "reading",
        "unread",
        "readed",
        "rereads",
        "reread",
        "dnf",
        "abandoned",
        "unfinished",
        "finished",
        "currently",
        # intent / wishlist
        "tbr",
        "wishlist",
        "wishlists",
        "wish",
        "want",
        "wanted",
        "buy",
        "buying",
        "purchase",
        "acquire",
        "maybe",
        # ownership / location
        "own",
        "owns",
        "owned",
        "owning",
        "have",
        "has",
        "possess",
        "borrowed",
        "borrow",
        "lent",
        "loaned",
        "library",
        "libraries",
        "shelf",
        "shelves",
        "shelved",
        "shelve",
        "bookshelf",
        "bookshelves",
        "bookcase",
        "storage",
        "boxed",
        "stored",
        # format / device — a real property of the copy, not of the work
        "kindle",
        "nook",
        "kobo",
        "ebook",
        "ebooks",
        "audible",
        "audio",
        "audiobook",
        "audiobooks",
        "paperback",
        "paperbacks",
        "hardback",
        "hardcover",
        "hardcovers",
        "pdf",
        "epub",
        "digital",
        "physical",
        "print",
        "printed",
        # personal curation
        "favorite",
        "favorites",
        "favourite",
        "favourites",
        "faves",
        "fave",
        "best",
        "worst",
        "loved",
        "hated",
        "disliked",
        "recommended",
        "recommendations",
        "rec",
        "recs",
        "dislike",
        "meh",
        "ugh",
        # site / shelf bookkeeping
        "goodreads",
        "shelfari",
        "librarything",
        "amazon",
        "calibre",
        "default",
        "misc",
        "miscellaneous",
        "unsorted",
        "uncategorized",
        "general",
        "stuff",
        "things",
        "list",
        "lists",
        "challenge",
        "challenges",
        "bookclub",
        "wishlisted",
        # first-person markers
        "my",
        "mine",
        "me",
        "i",
        "im",
        "ive",
        "our",
        "personal",
    }
)

#: Exact tags that survive tokenization but are still bookkeeping.
_STATUS_PHRASES = frozenset(
    {
        "to-read",
        "to-be-read",
        "not-read",
        "no-read",
        "on-hold",
        "on-my-shelf",
        "in-progress",
        "next-up",
        "series",
        "part-of-a-series",
        "first-in-series",
        "book-club",
        "books",
        "book",
        "novels",
        "novel",
        "fiction-books",
        "adult",
        "e-book",
        "all",
        "other",
        "various",
    }
)

#: A four-digit year anywhere in the tag means a reading log
#: (``read-in-2011``, ``2012-reads``). ``20th-century`` is unaffected: its
#: digits are not a standalone year.
_YEAR = re.compile(r"(?:^|[^0-9])(?:19|20)\d{2}(?:[^0-9]|$)")

#: Challenge/list tags like ``1001-books-to-read-before-you-die``.
_LEADING_COUNT = re.compile(r"^\d+[-_]")

_SEPARATORS = re.compile(r"[\s_/,.&+-]+")

MIN_TAG_LENGTH = 3
MAX_TAG_LENGTH = 40
#: rec-spec §11.2: "cap the number per book". Enough to characterize a book,
#: few enough that the tag line cannot dominate the description.
MAX_TAGS_PER_BOOK = 12


def tokenize(tag: str) -> tuple[str, ...]:
    return tuple(token for token in _SEPARATORS.split(tag.strip().lower()) if token)


def is_useful_tag(tag: str) -> bool:
    """Whether a single normalized tag describes the *book*."""
    normalized = tag.strip().lower()
    if not normalized:
        return False
    if len(normalized) < MIN_TAG_LENGTH or len(normalized) > MAX_TAG_LENGTH:
        return False
    if normalized in _STATUS_PHRASES:
        return False
    if _YEAR.search(normalized) or _LEADING_COUNT.match(normalized):
        return False

    tokens = tokenize(normalized)
    if not tokens:
        return False
    if any(token in _STATUS_TOKENS for token in tokens):
        return False
    # A tag that is only digits carries no meaning on its own.
    return not all(token.isdigit() for token in tokens)


def clean_tags(tags: Iterable[str], *, max_tags: int = MAX_TAGS_PER_BOOK) -> tuple[str, ...]:
    """Filter, de-duplicate and cap one book's tags, preserving input order.

    Input order is the caller's contract: the builder passes tags already
    sorted by support (how many readers used them), so the cap keeps the
    best-attested ones. De-duplication is on the normalized form, so
    ``Science Fiction`` and ``science-fiction`` cannot both occupy a slot.
    """
    seen: set[str] = set()
    kept: list[str] = []
    for tag in tags:
        normalized = tag.strip().lower()
        if not is_useful_tag(normalized):
            continue
        key = "-".join(tokenize(normalized))
        if key in seen:
            continue
        seen.add(key)
        kept.append(normalized)
        if len(kept) >= max_tags:
            break
    return tuple(kept)


def rejection_reason(tag: str) -> str | None:
    """Why a tag was dropped, for build reports and tests. ``None`` if kept.

    Exists so a build can report *what kind* of tags it discarded rather
    than only how many, which is what makes a rule change reviewable.
    """
    normalized = tag.strip().lower()
    if not normalized:
        return "empty"
    if len(normalized) < MIN_TAG_LENGTH:
        return "too-short"
    if len(normalized) > MAX_TAG_LENGTH:
        return "too-long"
    if normalized in _STATUS_PHRASES:
        return "bookkeeping-phrase"
    if _YEAR.search(normalized):
        return "reading-log-year"
    if _LEADING_COUNT.match(normalized):
        return "challenge-list"
    tokens = tokenize(normalized)
    if not tokens:
        return "empty"
    for token in tokens:
        if token in _STATUS_TOKENS:
            return f"bookkeeping-token:{token}"
    if all(token.isdigit() for token in tokens):
        return "numeric"
    return None


def summarize_rejections(tags: Sequence[str]) -> dict[str, int]:
    """Counts by rejection reason, for the build report."""
    counts: dict[str, int] = {}
    for tag in tags:
        reason = rejection_reason(tag)
        if reason is None:
            continue
        # Collapse the per-token detail so the summary stays readable.
        key = reason.split(":", 1)[0]
        counts[key] = counts.get(key, 0) + 1
    return counts
