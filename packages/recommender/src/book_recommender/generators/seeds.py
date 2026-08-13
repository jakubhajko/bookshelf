"""Turning a reader's context into weighted seed books (rec-spec §7.1, §20).

The CF and source-similarity generators all start from the same question —
*which books should this request retrieve from, and how much does each
count?* — and rec-spec §20 gives each surface a different answer:

============  ==================================================
Home          the reader's own strongest positive evidence
Shelf         the books on the target shelf (§20.2: extend the
              **shelf**, not the reader's entire global taste)
Similar       the source book alone (§20.3)
============  ==================================================

Keeping that in one module is what stops the three generators from drifting
into three subtly different notions of "seed", which would make their
provenance incomparable at fusion time.
"""

from __future__ import annotations

from dataclasses import dataclass

from book_recommender.config import (
    COLLABORATIVE_WEIGHTS_DEFAULT,
    GENERATOR_CONFIG_DEFAULT,
    CollaborativeSignalWeights,
    GeneratorConfig,
)
from book_recommender.contracts.context import (
    ShelfContext,
    SimilarBooksContext,
    SurfaceContext,
    UserContext,
)


@dataclass(frozen=True)
class Seed:
    """One book to retrieve from, and how strongly it counts."""

    book_id: int
    weight: float
    #: Which raw signal justified it, for diagnostics and reason codes.
    source: str


def collect_seeds(
    context: UserContext,
    surface: SurfaceContext,
    *,
    weights: CollaborativeSignalWeights = COLLABORATIVE_WEIGHTS_DEFAULT,
    config: GeneratorConfig = GENERATOR_CONFIG_DEFAULT,
) -> tuple[Seed, ...]:
    """Seed books for the CF/source generators on this surface.

    Ordered strongest first and capped at ``max_seed_books``, so the cap
    costs the weakest evidence rather than an arbitrary slice. Ties break on
    ``book_id`` to keep the selection deterministic for a fixed context —
    without that, a reader with forty equally-weighted saves would get a
    different seed set per process, and the persisted batch would stop being
    reproducible.
    """
    if isinstance(surface, SimilarBooksContext):
        # rec-spec §20.3: the source book is the entire query. Weight is
        # irrelevant with one seed, but 1.0 keeps aggregation uniform.
        return (Seed(book_id=surface.source_book_id, weight=1.0, source="source_book"),)

    rejected = set(context.not_interested_book_ids)

    if isinstance(surface, ShelfContext):
        # rec-spec §20.2. Shelf membership is the signal; a book's global
        # rating does not make it a stronger representative of *this* shelf.
        candidates = [
            Seed(book_id=book_id, weight=weights.shelf_save, source="target_shelf")
            for book_id in sorted(surface.shelf_book_ids)
            if book_id not in rejected
        ]
        return tuple(candidates[: config.max_seed_books])

    return _global_seeds(context, weights=weights, config=config, rejected=rejected)


def _global_seeds(
    context: UserContext,
    *,
    weights: CollaborativeSignalWeights,
    config: GeneratorConfig,
    rejected: set[int],
) -> tuple[Seed, ...]:
    """Home (and, for now, Search): the reader's own positive evidence.

    Search has no producer yet and rec-spec §7.1 gives submitted searches a
    CF weight of 0 — "query semantics when later used". Until that phase
    exists, a search surface seeds exactly like Home rather than returning
    nothing, which keeps the generator honest about having no query
    understanding instead of pretending the reader has no taste.
    """
    strongest: dict[int, Seed] = {}

    def offer(book_id: int, weight: float, source: str) -> None:
        # rec-spec §7.1: "For a book with multiple positive signals, avoid
        # uncontrolled double-counting. Define a deliberate combination
        # policy." Max-dominant, matching what R5 chose for the semantic
        # profile — a book both saved and rated 10/10 is strong evidence
        # once, not the sum of two independent readers liking it.
        if weight <= 0.0 or book_id in rejected:
            return
        current = strongest.get(book_id)
        if current is None or weight > current.weight:
            strongest[book_id] = Seed(book_id=book_id, weight=weight, source=source)

    for seed in context.taste_seeds:
        offer(seed.book_id, weights.taste_seed, "taste_seed")
    for rating in context.ratings:
        offer(rating.book_id, weights.for_rating(rating.rating_value), "rating")
    for saved in context.saved_books:
        offer(saved.book_id, weights.shelf_save, "shelf_save")

    ordered = sorted(strongest.values(), key=lambda seed: (-seed.weight, seed.book_id))
    return tuple(ordered[: config.max_seed_books])
