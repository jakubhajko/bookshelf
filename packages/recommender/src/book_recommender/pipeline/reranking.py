"""Surface-specific reranking for UX diversity (rec-spec §19, ADR-0017).

A ranked list optimized purely for relevance collapses. The best twenty
books for a reader who likes Dune are frequently twenty Dune books, each one
individually correct and the set as a whole useless. Reranking trades a
little per-item relevance for a better *set*.

Greedy and deterministic rather than learned (rec-spec §19): pick the best
remaining candidate, then re-penalize everything that resembles what has
been picked, and repeat. Penalties depend on what is already selected, which
is what makes this different from a second sort.

The amount of diversity is a property of the **surface**, not the model, and
getting that wrong in either direction is a product failure:

======== ============================================================
Home     strongest — broad discovery across the reader's interests,
         plus a small controlled exploration allowance
Shelf    lighter — coherence with the target shelf matters more than
         topic breadth
Similar  very light — a reader asking "what is like this book" and
         receiving deliberately dissimilar books has been failed
======== ============================================================

rec-spec §19 is explicit for Similar Books: "do not aggressively suppress
same-author items if they are genuinely relevant." Someone who just read
*Dune* is not badly served by *Dune Messiah*.

**Exploration is not popularity.** rec-spec §15 calls conflating them out
specifically, because doing so makes "exploration" mean "show more
bestsellers". The reserved slots here go to candidates from interests that
are *not* already represented, which is the opposite policy.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from book_recommender.artifacts.content import ContentEmbeddings
from book_recommender.artifacts.item_metadata import ItemMetadataRow, ItemMetadataTable
from book_recommender.config import SurfaceConfig
from book_recommender.pipeline.ranking import RankedCandidate

#: A trailing series marker, e.g. "Dune Messiah (Dune Chronicles #2)" or
#: "The Fellowship of the Ring (The Lord of the Rings, #1)". Deliberately
#: conservative: rec-spec §19 says "repeated series where detectable", and a
#: loose pattern that groups unrelated books is worse than missing some.
_SERIES = re.compile(r"\(([^)]*?)[,]?\s*#[\d.]+\)\s*$")


def series_of(title: str) -> str | None:
    """The series name in a title, or ``None`` when there is no marker."""
    match = _SERIES.search(title)
    if match is None:
        return None
    name = match.group(1).strip().lower()
    return name or None


_PUNCTUATION = re.compile(r"[^a-z0-9 ]+")
_WHITESPACE = re.compile(r"\s+")


def duplicate_key(title: str, author: str) -> tuple[str, str] | None:
    """A work-identity key: normalized title plus author.

    **Cosine cannot do this job, which was measured rather than assumed.**
    The live catalog holds `#58203 'Dune'` and `#67405 'Dune *'` as separate
    works (risk #112), and their embeddings are only 0.7246 apart — *less*
    similar than 'Dune' is to 'Dune Messiah' at 0.8092. A threshold low
    enough to catch the duplicate would suppress the sequels, which on
    Similar Books are the correct answer.

    The reason is straightforward in hindsight: the duplicate row has 69
    ratings against 16,541, so it carries a thinner description and fewer
    shelf tags, and the encoder faithfully represents *that text*. The two
    rows are near-duplicate in **work identity**, not in content — so
    identity is what has to be compared.

    Returns ``None`` when there is not enough to compare, which is safer
    than a key that collides on emptiness: ~2,300 catalog books have no
    author, and grouping all of them as one work would be catastrophic.
    """
    normalized = _WHITESPACE.sub(" ", _PUNCTUATION.sub("", title.strip().lower())).strip()
    name = author.strip().lower()
    if not normalized or not name:
        return None
    return (normalized, name)


@dataclass(frozen=True)
class RerankContext:
    """Artifact-backed lookups the reranker needs.

    Both are optional, and their absence degrades rather than fails
    (rec-spec §27): without embeddings there is no near-duplicate detection,
    without metadata no author or series control. The interest and source
    penalties keep working either way, since those read provenance the
    candidates already carry.
    """

    surface: SurfaceConfig
    embeddings: ContentEmbeddings | None = None
    metadata: ItemMetadataTable | None = None
    #: Books that count as *already present* for near-duplicate purposes
    #: without occupying a slot — on Similar Books, the source book itself.
    #:
    #: Found by the live smoke test rather than by reasoning: the reranker
    #: compares each candidate against what it has already **selected**, and
    #: the source book is excluded from the results, so it was never in that
    #: set. Similar-to-*Dune* therefore returned `'Dune *'` — the catalog's
    #: near-duplicate row for the same work (risk #112) — at rank 10, which
    #: is the single worst recommendation that surface can make: the book
    #: the reader is already looking at.
    #:
    #: These seed the duplicate check only. They deliberately do *not* feed
    #: the author or series counters, because rec-spec §19 says not to
    #: aggressively suppress same-author items on Similar Books — the Dune
    #: sequels are the right answer there, and only another *Dune* is not.
    reference_book_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class RerankedCandidate:
    """A selected candidate and what reranking did to it.

    ``penalty`` and ``reasons`` exist so a diagnostic can answer "why is
    this eleventh rather than second?" — rec-spec §19's tunables are only
    tunable if their effect is visible. ADR-0017 warns against putting a
    blob on all 60 rows by default, so this stays small: a float and a few
    short strings.
    """

    book_id: int
    #: Position in the final authoritative order, 1-based.
    position: int
    ranked: RankedCandidate
    penalty: float = 0.0
    reasons: tuple[str, ...] = field(default_factory=tuple)
    #: True when this filled one of the surface's exploration slots.
    exploration: bool = False

    @property
    def score(self) -> float:
        return self.ranked.score - self.penalty


class Reranker(Protocol):
    def rerank(
        self, candidates: Sequence[RankedCandidate], *, context: RerankContext, limit: int
    ) -> tuple[RerankedCandidate, ...]: ...


@dataclass(frozen=True)
class _CandidateFacts:
    """Everything about one candidate that selection cannot change.

    Read once per candidate instead of once per candidate per step. The
    difference is not cosmetic: a Home batch is 60 slots over ~600
    candidates, so the naive loop parses the same title with two regexes
    36,000 times and reads the same embedding row 36,000 times.
    """

    author: str
    series: str | None
    key: tuple[str, str] | None
    interest: str
    source: str
    #: False when this book has no embedding — books added to the catalog
    #: since the content artifact was built. Its duplicate similarity is
    #: never compared, exactly as before.
    has_vector: bool


class DiversityReranker:
    """Greedy MMR-like selection under the surface's diversity policy.

    **Greedy, but not quadratic in vector work.** The selection rule is
    unchanged from the obvious implementation — at each step, penalize every
    remaining candidate by what has already been chosen and take the best —
    but the near-duplicate term is maintained incrementally. A candidate's
    duplicate penalty depends on ``max(cosine to each selected book)``, and
    a max over a growing set only ever needs the new member: one
    matrix-vector product against all remaining candidates per selection
    step, rather than one matrix rebuild per candidate per step. The
    arithmetic is identical; on a real Home batch it is the difference
    between ~450 ms and ~15 ms (plan.md §5s).
    """

    def rerank(
        self,
        candidates: Sequence[RankedCandidate],
        *,
        context: RerankContext,
        limit: int,
    ) -> tuple[RerankedCandidate, ...]:
        if not candidates or limit <= 0:
            return ()

        config = context.surface.rerank
        remaining = list(candidates)
        selected: list[RerankedCandidate] = []

        vectors, facts = self._prepare(remaining, context)
        remaining_facts = list(facts)

        # Selection state, all keyed on what has already been chosen.
        authors: dict[str, int] = {}
        series: dict[str, int] = {}
        interests: dict[str, int] = {}
        sources: dict[str, int] = {}
        chosen_keys: set[tuple[str, str]] = set()
        # Best cosine from each remaining candidate to anything already
        # chosen. -inf means "nothing to compare against yet", which is
        # distinct from a genuine similarity of 0.
        best_similarity = np.full(len(remaining), -np.inf, dtype=np.float64)

        # Both duplicate checks are seeded with the surface's reference
        # books, so a candidate duplicating the source book is caught before
        # anything at all has been selected.
        for book_id in context.reference_book_ids:
            row = self._metadata_row(book_id, context)
            key = None if row is None else duplicate_key(row.title, row.author)
            if key is not None:
                chosen_keys.add(key)
            vector = self._vector(book_id, context)
            if vector is not None and vectors is not None:
                np.maximum(best_similarity, vectors @ vector, out=best_similarity)

        explore_after = max(limit - config.exploration_slots, 0)

        while remaining and len(selected) < limit:
            want_exploration = (
                config.exploration_slots > 0 and len(selected) >= explore_after and bool(interests)
            )

            best_index = 0
            best_value = -np.inf
            best_penalty = 0.0
            best_reasons: tuple[str, ...] = ()

            for index, candidate in enumerate(remaining):
                penalty, reasons = self._penalty(
                    candidate,
                    facts=remaining_facts[index],
                    similarity=float(best_similarity[index]),
                    context=context,
                    authors=authors,
                    series=series,
                    interests=interests,
                    sources=sources,
                    chosen_keys=chosen_keys,
                )
                value = candidate.score - penalty
                if want_exploration and remaining_facts[index].interest in interests:
                    # Reserved slots go to an interest not yet represented —
                    # rec-spec §15's exploration, which is about coverage and
                    # has nothing to do with popularity.
                    value -= 1e6
                if value > best_value:
                    best_index, best_value = index, value
                    best_penalty, best_reasons = penalty, reasons

            candidate = remaining.pop(best_index)
            chosen = remaining_facts.pop(best_index)
            chosen_vector = (
                vectors[best_index].copy() if vectors is not None and chosen.has_vector else None
            )
            best_similarity = np.delete(best_similarity, best_index)
            if vectors is not None:
                vectors = np.delete(vectors, best_index, axis=0)
            selected.append(
                RerankedCandidate(
                    book_id=candidate.book_id,
                    position=len(selected) + 1,
                    ranked=candidate,
                    penalty=best_penalty,
                    reasons=best_reasons,
                    exploration=want_exploration and chosen.interest not in interests,
                )
            )

            if chosen.author:
                authors[chosen.author] = authors.get(chosen.author, 0) + 1
            if chosen.series:
                series[chosen.series] = series.get(chosen.series, 0) + 1
            if chosen.key is not None:
                chosen_keys.add(chosen.key)
            interests[chosen.interest] = interests.get(chosen.interest, 0) + 1
            sources[chosen.source] = sources.get(chosen.source, 0) + 1
            # One matrix-vector product folds the newly selected book into
            # every remaining candidate's running maximum. This is the whole
            # optimization: `max` over a growing set only needs its newest
            # member.
            if vectors is not None and chosen_vector is not None:
                np.maximum(best_similarity, vectors @ chosen_vector, out=best_similarity)

        return tuple(selected)

    # --- preparation ------------------------------------------------------

    def _prepare(
        self, candidates: Sequence[RankedCandidate], context: RerankContext
    ) -> tuple[np.ndarray | None, tuple[_CandidateFacts, ...]]:
        """Per-candidate constants, and their vectors as one dense matrix.

        The matrix is row-aligned with the candidate list — a candidate
        without an embedding gets a zero row and ``has_vector=False``, so its
        similarity is never compared. Padding rather than compaction keeps
        row *i* the vector of candidate *i*, which is what lets a selection
        delete from the list, the matrix and the running maximum with one
        index.
        """
        embeddings: ContentEmbeddings | None = context.embeddings
        facts: list[_CandidateFacts] = []
        rows: list[np.ndarray] = []
        dimension = 0

        for candidate in candidates:
            row = self._metadata_row(candidate.book_id, context)
            vector = self._vector(candidate.book_id, context)
            if vector is not None:
                dimension = vector.size
            rows.append(vector if vector is not None else np.empty(0))
            facts.append(
                _CandidateFacts(
                    author=row.author if row is not None else "",
                    series=series_of(row.title) if row is not None else None,
                    key=duplicate_key(row.title, row.author) if row is not None else None,
                    interest=self._interest_of(candidate),
                    source=(
                        candidate.fused.sources[0].generator if candidate.fused.sources else ""
                    ),
                    has_vector=vector is not None,
                )
            )

        if embeddings is None or dimension == 0:
            return (None, tuple(facts))

        matrix = np.zeros((len(candidates), dimension), dtype=np.float64)
        for index, vector in enumerate(rows):
            if vector.size:
                matrix[index] = vector
        return (matrix, tuple(facts))

    # --- penalties --------------------------------------------------------

    def _penalty(
        self,
        candidate: RankedCandidate,
        *,
        facts: _CandidateFacts,
        similarity: float,
        context: RerankContext,
        authors: dict[str, int],
        series: dict[str, int],
        interests: dict[str, int],
        sources: dict[str, int],
        chosen_keys: set[tuple[str, str]],
    ) -> tuple[float, tuple[str, ...]]:
        config = context.surface.rerank
        penalty = 0.0
        reasons: list[str] = []

        if facts.key is not None and facts.key in chosen_keys and config.near_duplicate_penalty:
            # Same work under a different catalog row. Cosine misses this
            # entirely — see `duplicate_key` for the measurement.
            penalty += config.near_duplicate_penalty
            reasons.append("duplicate work")
        seen_author = authors.get(facts.author, 0) if facts.author else 0
        if seen_author and config.author_penalty:
            penalty += config.author_penalty * seen_author
            reasons.append(f"author x{seen_author}")
        seen_series = series.get(facts.series, 0) if facts.series else 0
        if seen_series and config.series_penalty:
            penalty += config.series_penalty * seen_series
            reasons.append(f"series x{seen_series}")

        seen_interest = interests.get(facts.interest, 0)
        if seen_interest and config.interest_concentration_penalty:
            penalty += config.interest_concentration_penalty * seen_interest
            reasons.append(f"interest x{seen_interest}")

        seen_source = sources.get(facts.source, 0)
        if seen_source and config.source_concentration_penalty:
            penalty += config.source_concentration_penalty * seen_source
            reasons.append(f"source x{seen_source}")

        if (
            config.near_duplicate_penalty
            and facts.has_vector
            and similarity >= config.near_duplicate_threshold
        ):
            # The 'Dune' / 'Dune *' case: a genuinely separate catalog row
            # for what is effectively the same work.
            penalty += config.near_duplicate_penalty
            reasons.append(f"near-duplicate {similarity:.2f}")

        return penalty, tuple(reasons)

    @staticmethod
    def _interest_of(candidate: RankedCandidate) -> str:
        """Which query strategy best explains this candidate.

        Read from the strongest contributing source's provenance, so a book
        found via ``interest:i1`` is spread against other ``interest:i1``
        books. Candidates from non-semantic generators share the generator
        name, which is coarse but honest — the source graph does not know
        which interest it was serving.
        """
        if not candidate.fused.sources:
            return ""
        return candidate.fused.sources[0].provenance

    @staticmethod
    def _metadata_row(book_id: int, context: RerankContext) -> ItemMetadataRow | None:
        table: ItemMetadataTable | None = context.metadata
        return None if table is None else table.get(book_id)

    @staticmethod
    def _vector(book_id: int, context: RerankContext) -> np.ndarray | None:
        embeddings: ContentEmbeddings | None = context.embeddings
        if embeddings is None:
            return None
        vector = embeddings.vector_for(book_id)
        return None if vector is None else np.asarray(vector, dtype=np.float64)
