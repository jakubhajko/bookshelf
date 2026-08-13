"""The candidate-generator contract (rec-spec §16).

Five generators produce five ranked lists that Phase R7 fuses with weighted
RRF. This module defines what all five agree on: the identity vocabulary,
the shape of a candidate, the shape of a result, and the protocol itself.

Three properties are load-bearing and are tested for every generator:

**Rank is 1-based and dense.** RRF divides by ``rrf_k + rank`` (ADR-0017),
so a rank that starts at 0 or skips values silently changes every fusion
weight. The generators do not compute their own ranks — :func:`rank_all`
does, exactly once.

**A generator never returns the same book twice.** Fusion deduplicates
*across* generators; a duplicate *within* one would be counted twice at the
same rank and would inflate that book's fused score.

**A generator never invents work.** It sees an immutable request and
artifacts loaded at construction. No database, no clock, no I/O — the same
inputs must give the same output, because the engine's order is
authoritative and gets persisted (ADR-0006, ADR-0007).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from book_recommender.contracts.context import SurfaceContext, UserContext
from book_recommender.profiling import InterestProfile


class GeneratorId(StrEnum):
    """The five V1 candidate families (CLAUDE.md, rec-spec §9-§15).

    Centralized because these strings escape the package: they become
    ``candidate_sources`` on persisted recommendation rows, keys in
    per-surface RRF weight tables (R7), and diagnostic field names. A
    generator that spelled its own name inline would let a rename silently
    orphan a surface weight.
    """

    ALS = "als"
    ITEM_CF = "item_cf"
    SEMANTIC = "semantic"
    SOURCE_SIMILARITY = "source_similarity"
    POPULARITY = "popularity"


class GeneratorStatus(StrEnum):
    """Why a generator returned what it returned.

    An empty candidate list has several completely different causes, and
    rec-spec §27 requires the difference be visible rather than inferred:
    "ALS artifact absent" is an operational problem, "this reader has no
    evidence yet" is a cold-start path, and "this generator does not run on
    this surface" is correct behaviour. Collapsing them into "empty" would
    make the first invisible.
    """

    OK = "ok"
    #: The generator has no artifact to work from. rec-spec §27: do not hide
    #: this — the pipeline continues, but something needs rebuilding.
    NO_ARTIFACT = "no_artifact"
    #: The artifact is fine; this reader supplied nothing to retrieve from.
    NO_EVIDENCE = "no_evidence"
    #: rec-spec §20.3: ALS has no place on Similar Books. Not a failure.
    NOT_APPLICABLE = "not_applicable"
    #: Retrieval ran and legitimately matched nothing eligible.
    EMPTY = "empty"
    #: The generator raised. rec-spec §16: isolate the failure, keep the
    #: pipeline alive if enough other sources remain.
    FAILED = "failed"


#: Provenance strings for query strategies that are not simply the generator
#: name. rec-spec §16 asks for a "source/provenance identifier"; rec-spec §21
#: requires reasons stay truthful, which means a candidate must be able to
#: say *which* interest or shelf produced it, not merely "semantic".
PROVENANCE_INTEREST = "interest"
PROVENANCE_SHELF = "shelf"
PROVENANCE_TARGET_SHELF = "target_shelf"
PROVENANCE_SOURCE_BOOK = "source_book"
PROVENANCE_GLOBAL = "global"


@dataclass(frozen=True)
class Candidate:
    """One retrieved book, with where it came from and how it ranked there.

    ``score`` is the generator's own raw score and is **not comparable
    across generators** — an ALS dot product, a cosine similarity and an
    aggregated edge weight share no scale. That incomparability is the whole
    reason ADR-0017 chose RRF, which reads ``rank`` and ignores ``score``.
    The score is carried anyway because rec-spec §17 requires the raw score
    per source be preserved into persistence, and because it is what makes a
    diagnostic readable.

    ``score`` is ``None`` where the generator genuinely has no meaningful
    score — the source-similarity graph stores edge ranks, not weights.
    """

    book_id: int
    generator: GeneratorId
    #: 1-based position within this generator's own list.
    rank: int
    score: float | None
    #: Which query strategy produced it. The generator name for the
    #: single-strategy generators; ``"interest:i1"``-style for semantic.
    provenance: str
    #: Compact per-candidate context. Kept small on purpose: ADR-0017 warns
    #: against putting a diagnostics blob on all 60 rows of every batch.
    diagnostics: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class GeneratorResult:
    """One generator's ranked list plus why it looks like that."""

    generator: GeneratorId
    candidates: tuple[Candidate, ...] = ()
    status: GeneratorStatus = GeneratorStatus.OK
    #: Generator-level diagnostics: seed counts, query counts, artifact
    #: version. Never raw vectors and never user-identifying data
    #: (CLAUDE.md: diagnostics must not become a sensitive-data dump).
    diagnostics: Mapping[str, object] = field(default_factory=dict)

    @property
    def book_ids(self) -> tuple[int, ...]:
        return tuple(candidate.book_id for candidate in self.candidates)

    @property
    def is_empty(self) -> bool:
        return not self.candidates


@dataclass(frozen=True)
class GeneratorRequest:
    """Everything a generator may read (rec-spec §16, §8).

    Immutable, and assembled by the application *before* it ends its read
    transaction — CLAUDE.md's "no open DB transaction during recommendation
    inference". A generator holding this cannot reach PostgreSQL because
    there is nothing here to reach it with.

    ``semantic_profile`` is derived state rather than raw context: it is
    recomputed per fresh batch from the content artifact (rec-spec §12), so
    it arrives per request rather than at construction like the artifacts.
    It is ``None`` when the content artifact is unavailable or the reader
    has no positive evidence — the semantic generator then reports
    ``NO_ARTIFACT``/``NO_EVIDENCE`` rather than guessing.
    """

    user_context: UserContext
    surface_context: SurfaceContext
    #: How many candidates to retrieve. rec-spec §24: generators over-
    #: retrieve well past the final 60 so fusion has a pool to work with.
    #: The quota is the *caller's* decision (surface configuration, R7), not
    #: the generator's.
    count: int
    #: Application-owned eligibility, already resolved to book ids
    #: (CLAUDE.md: eligibility rules stay outside the recommender). Hard
    #: exclusions, session exclusions and any surface-specific exclusion are
    #: already unioned here — a generator applies this set and does not
    #: reason about where it came from.
    excluded_book_ids: frozenset[int] = frozenset()
    semantic_profile: InterestProfile | None = None


class CandidateGenerator(Protocol):
    """Structural protocol, matching the package's existing engine/provider
    style (rec-spec §16: "consistent with the existing recommender package
    style").

    Structural rather than an ABC so a test double is just a class with the
    right two members, and so no generator inherits behaviour it did not ask
    for.
    """

    @property
    def generator_id(self) -> GeneratorId: ...

    def generate(self, request: GeneratorRequest) -> GeneratorResult: ...


def rank_all(
    scored: Iterable[tuple[int, float | None]],
    *,
    generator: GeneratorId,
    provenance: str,
    limit: int,
    excluded_book_ids: frozenset[int] = frozenset(),
    diagnostics_for: Mapping[int, Mapping[str, object]] | None = None,
) -> tuple[Candidate, ...]:
    """Turn an already-ordered ``(book_id, score)`` sequence into candidates.

    The single place ranks are assigned, exclusions are applied and
    duplicates are dropped, so all five generators cannot disagree about any
    of the three. Input order is trusted and preserved — every caller has
    already sorted deterministically, and re-sorting here would silently
    override a generator that had a reason for its order.
    """
    candidates: list[Candidate] = []
    seen: set[int] = set()
    for book_id, score in scored:
        if len(candidates) >= limit:
            break
        if book_id in excluded_book_ids or book_id in seen:
            continue
        seen.add(book_id)
        extra = (diagnostics_for or {}).get(book_id, {})
        candidates.append(
            Candidate(
                book_id=book_id,
                generator=generator,
                rank=len(candidates) + 1,
                score=score,
                provenance=provenance,
                diagnostics=dict(extra),
            )
        )
    return tuple(candidates)


def interleave(
    ranked_lists: Sequence[tuple[str, Sequence[tuple[int, float]]]],
    *,
    generator: GeneratorId,
    limit: int,
    excluded_book_ids: frozenset[int] = frozenset(),
) -> tuple[Candidate, ...]:
    """Round-robin several ranked lists into one, best-of-each first.

    Used by the semantic generator, which issues one query per interest and
    per shelf. Merging those by raw cosine score would let the single
    tightest cluster take every slot — a reader with a dense Dune shelf and
    a sparse poetry shelf would get Dune, which defeats the entire point of
    inferring *multiple* interests (rec-spec §12.2).

    Round-robin gives each query its first result before any query gets its
    second. The lists are visited in the caller's order, so a caller that
    sorts queries by weight gets weight priority within each round without
    this function needing to know what a weight is.

    A book reachable from several queries keeps its **first** appearance,
    which is its best rank across the queries that found it, and records the
    others in ``diagnostics`` — provenance is preserved, not discarded
    (rec-spec §21).
    """
    if limit <= 0:
        return ()

    contributors: dict[int, list[str]] = {}
    order: list[tuple[int, float, str]] = []
    seen: set[int] = set()
    depth = max((len(items) for _, items in ranked_lists), default=0)

    for position in range(depth):
        for provenance, items in ranked_lists:
            if position >= len(items):
                continue
            book_id, score = items[position]
            if book_id in excluded_book_ids:
                continue
            contributors.setdefault(book_id, []).append(provenance)
            if book_id in seen:
                continue
            seen.add(book_id)
            order.append((book_id, score, provenance))

    # Trimming after the full pass rather than breaking early, so a book's
    # `queries` count reflects every query that actually found it.
    candidates: list[Candidate] = []
    for book_id, score, provenance in order[:limit]:
        sources = contributors.get(book_id, [provenance])
        diagnostics: dict[str, object] = {}
        if len(sources) > 1:
            diagnostics["queries"] = len(sources)
            diagnostics["also_from"] = tuple(sources[1:])
        candidates.append(
            Candidate(
                book_id=book_id,
                generator=generator,
                rank=len(candidates) + 1,
                score=score,
                provenance=provenance,
                diagnostics=diagnostics,
            )
        )
    return tuple(candidates)
