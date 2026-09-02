"""Counting near-duplicate works in the catalog (risk #117, ADR-0024).

ADR-0024 gave the reranker an *exact* work-identity key — normalized title
plus author — after measuring that cosine similarity cannot separate a
duplicate row from a sequel. It also rejected fuzzy matching as premature,
on the explicit grounds that fuzzy matching adds a threshold and a
false-positive class "to fix a problem of unmeasured size".

This module measures the size. It does not decide anything: deduplicating at
import time is a catalog change with consequences for ratings, shelves and
permalinks, and that decision needs the number first.

**The three tiers are a bracket, not three attempts at one answer.**

``exact``
    What the shipped reranker actually collapses. A lower bound.

``edition``
    Additionally ignores parenthesized and bracketed segments and a short
    list of edition words. ``'Dune (Dune Chronicles #1)'`` joins ``'Dune'``;
    ``'Dune Messiah'`` still does not. Conservative enough to be a candidate
    rule, which is why its groups are worth reading individually.

``subtitle``
    Additionally drops everything after the first colon. This one is an
    **upper bound with a known false-positive class**: it correctly joins
    ``'Dune: 40th Anniversary Edition'`` to ``'Dune'``, and it incorrectly
    joins ``'Star Wars: A New Hope'`` to ``'Star Wars: The Empire Strikes
    Back'``. It is reported so nobody has to guess how much room lies above
    the conservative tier — never as a rule to ship.

Every tier keeps the author, because a title alone collides across genuinely
different works, and books with no author are excluded entirely for the
reason :func:`duplicate_key` gives: ~2,300 catalog rows have none, and one
group of 2,300 "duplicates" would be worse than no measurement.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from book_recommender.artifacts.item_metadata import ItemMetadataRow, ItemMetadataTable
from book_recommender.pipeline.reranking import duplicate_key

#: Parenthesized or bracketed segments: series markers, edition notes,
#: translated titles. Removed before normalization in the looser tiers.
_BRACKETED = re.compile(r"[(\[][^)\]]*[)\]]")
#: Trailing edition/format words, with or without an ordinal in front.
_EDITION_SUFFIX = re.compile(
    r"\b(\d+(st|nd|rd|th)\s+)?"
    r"(anniversary|collectors?|deluxe|revised|reissue|reprint|illustrated|"
    r"unabridged|abridged|annotated|special|movie tie[- ]?in|boxed set|"
    r"international|paperback|hardcover)\b.*$"
)
_PUNCTUATION = re.compile(r"[^a-z0-9 ]+")
_WHITESPACE = re.compile(r"\s+")

EXACT = "exact"
EDITION = "edition"
SUBTITLE = "subtitle"
TIERS: tuple[str, ...] = (EXACT, EDITION, SUBTITLE)


def _normalize(title: str) -> str:
    return _WHITESPACE.sub(" ", _PUNCTUATION.sub("", title.strip().lower())).strip()


def tier_key(title: str, author: str, *, tier: str) -> tuple[str, str] | None:
    """Work-identity key at one tier, or ``None`` when it cannot be formed."""
    if tier == EXACT:
        return duplicate_key(title, author)

    text = _BRACKETED.sub(" ", title)
    if tier == SUBTITLE:
        text = text.split(":", 1)[0]
    text = _EDITION_SUFFIX.sub("", _normalize(text)).strip()
    name = author.strip().lower()
    if not text or not name:
        return None
    return (text, name)


@dataclass(frozen=True)
class DuplicateGroup:
    """Books sharing one work-identity key."""

    key: tuple[str, str]
    book_ids: tuple[int, ...]
    titles: tuple[str, ...]

    @property
    def size(self) -> int:
        return len(self.book_ids)

    def as_dict(self) -> dict[str, object]:
        return {
            "title": self.key[0],
            "author": self.key[1],
            "book_ids": list(self.book_ids),
            "titles": list(self.titles),
        }


@dataclass(frozen=True)
class TierResult:
    tier: str
    #: Keys with two or more books.
    groups: int
    #: Books inside those groups.
    books: int
    #: Books that would disappear if each group collapsed to one row.
    redundant: int
    largest_group: int
    samples: tuple[DuplicateGroup, ...]

    def share_of(self, catalog_size: int) -> float:
        return self.redundant / catalog_size if catalog_size else 0.0

    def as_dict(self, *, catalog_size: int) -> dict[str, object]:
        return {
            "tier": self.tier,
            "groups": self.groups,
            "books": self.books,
            "redundant": self.redundant,
            "redundant_share": round(self.share_of(catalog_size), 5),
            "largest_group": self.largest_group,
            "samples": [group.as_dict() for group in self.samples],
        }


@dataclass(frozen=True)
class DuplicateReport:
    catalog_size: int
    #: Books with no usable key — no title or no author.
    unkeyable: int
    tiers: tuple[TierResult, ...]

    def tier(self, name: str) -> TierResult | None:
        for result in self.tiers:
            if result.tier == name:
                return result
        return None

    def as_dict(self) -> dict[str, object]:
        return {
            "catalog_size": self.catalog_size,
            "unkeyable": self.unkeyable,
            "tiers": [tier.as_dict(catalog_size=self.catalog_size) for tier in self.tiers],
        }


def duplicate_report(
    rows: Iterable[ItemMetadataRow] | ItemMetadataTable,
    *,
    tiers: Sequence[str] = TIERS,
    samples: int = 12,
) -> DuplicateReport:
    """Count duplicate-work groups at each tier over the whole catalog."""
    materialized = list(rows.rows() if isinstance(rows, ItemMetadataTable) else rows)
    groups: dict[str, dict[tuple[str, str], list[ItemMetadataRow]]] = {
        tier: defaultdict(list) for tier in tiers
    }
    unkeyable = 0

    for row in materialized:
        keyed = False
        for tier in tiers:
            key = tier_key(row.title, row.author, tier=tier)
            if key is not None:
                groups[tier][key].append(row)
                keyed = True
        if not keyed:
            unkeyable += 1

    results: list[TierResult] = []
    for tier in tiers:
        collisions = {key: members for key, members in groups[tier].items() if len(members) > 1}
        # Largest first, then by key, so the sample is the most interesting
        # groups rather than whichever hashed first.
        ordered = sorted(collisions.items(), key=lambda item: (-len(item[1]), item[0]))
        results.append(
            TierResult(
                tier=tier,
                groups=len(collisions),
                books=sum(len(members) for members in collisions.values()),
                redundant=sum(len(members) - 1 for members in collisions.values()),
                largest_group=max((len(members) for members in collisions.values()), default=0),
                samples=tuple(
                    DuplicateGroup(
                        key=key,
                        book_ids=tuple(member.book_id for member in members),
                        titles=tuple(member.title for member in members),
                    )
                    for key, members in ordered[:samples]
                ),
            )
        )

    return DuplicateReport(
        catalog_size=len(materialized), unkeyable=unkeyable, tiers=tuple(results)
    )
