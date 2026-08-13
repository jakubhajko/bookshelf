"""Deterministic, versioned book text for the encoder (rec-spec §11.2).

One function, one output, no randomness and no I/O: the same book always
produces the same string. That is what makes an embedding artifact
reproducible, and it is why the template version is recorded in the
manifest — a change here changes every vector, and the artifact has to be
able to say so.

The structure follows rec-spec §11.2's recommendation:

```text
Title: ...
Author: ...
Genres: ...
Themes: ...
Description:
...
```

**What is deliberately absent** (rec-spec §11.2's "Do not embed" list):
ratings, popularity counts, ISBNs, page counts, publication years and raw
ids. Those are ranking features, not semantics. Embedding "4.27 average
rating" would let the encoder cluster books by popularity and would make
the nearest-neighbour space partly a bestseller list.

The description is the dominant field and comes last, so that truncation at
the encoder's token limit removes description tail rather than the title or
author — the fields most likely to be discriminative are the ones
guaranteed to survive.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

#: Bump when the template below changes the output for any realistic input.
TEXT_TEMPLATE_VERSION = "booktext-v1"

#: Characters, not tokens — a cheap deterministic bound applied before the
#: encoder's own tokenizer truncation, so the text stored in a build report
#: matches what was encoded. Roughly 512 tokens of English prose.
MAX_DESCRIPTION_CHARS = 1800
MAX_TITLE_CHARS = 200
MAX_AUTHOR_CHARS = 120
MAX_GENRES = 5


@dataclass(frozen=True)
class BookText:
    """The text encoded for one book, plus what went into it."""

    text: str
    used_description: bool
    tag_count: int
    genre_count: int

    def __len__(self) -> int:
        return len(self.text)


def build_book_text(
    *,
    title: str,
    author: str | None = None,
    genres: Sequence[str] = (),
    tags: Sequence[str] = (),
    description: str | None = None,
) -> BookText:
    """Compose the encoder input for one book.

    Empty fields are omitted entirely rather than emitted as
    ``Author:`` with nothing after it: a dangling label is noise the encoder
    would otherwise have to interpret, and ~2,300 catalog books have no
    author at all.
    """
    lines: list[str] = [f"Title: {_clip(title, MAX_TITLE_CHARS)}"]

    clean_author = _clip((author or "").strip(), MAX_AUTHOR_CHARS)
    if clean_author:
        lines.append(f"Author: {clean_author}")

    selected_genres = [genre.strip() for genre in genres if genre and genre.strip()][:MAX_GENRES]
    if selected_genres:
        lines.append(f"Genres: {', '.join(selected_genres)}")

    selected_tags = [tag.strip() for tag in tags if tag and tag.strip()]
    if selected_tags:
        # "Themes" rather than "Tags": the cleaned set is thematic by
        # construction, and the label is part of what the encoder reads.
        lines.append(f"Themes: {', '.join(selected_tags)}")

    clean_description = _normalize_whitespace(description or "")
    if clean_description:
        lines.append("Description:")
        lines.append(_clip(clean_description, MAX_DESCRIPTION_CHARS))

    return BookText(
        text="\n".join(lines),
        used_description=bool(clean_description),
        tag_count=len(selected_tags),
        genre_count=len(selected_genres),
    )


def _normalize_whitespace(value: str) -> str:
    """Collapse runs of whitespace so that formatting noise in the source
    description cannot change the embedding of otherwise identical text."""
    return " ".join(value.split())


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    # Cut on a word boundary when one is close, so the text does not end
    # mid-word — deterministic either way.
    truncated = value[:limit]
    space = truncated.rfind(" ")
    if space > limit - 40:
        truncated = truncated[:space]
    return truncated.rstrip() + "…"
