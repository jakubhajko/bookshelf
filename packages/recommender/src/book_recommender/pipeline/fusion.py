"""Weighted Reciprocal Rank Fusion (rec-spec §17, ADR-0017).

Five generators return five ranked lists whose scores share no scale: an
ALS dot product of latent factors, a cosine similarity in [-1, 1], an
item-item similarity whose range depends on the weighting, an aggregated
graph edge weight, and a Bayesian-shrunk mean rating. Normalizing those onto
a common scale needs a distributional assumption none of them satisfies, and
the assumption would then hide inside the tuned weights.

RRF sidesteps it entirely by reading only *rank*:

.. code-block:: text

    fusion_score(i) = Σ_g weight(surface, g) / (rrf_k + rank_g(i))

Two consequences are worth stating because they are the reasons to prefer
it. It rewards agreement — a book three generators found beats a book one
generator ranked first — and it is immune to a generator whose scores are
badly calibrated, because it never reads them.

What RRF cannot fix is a rank that is itself arbitrary. Where a generator
produces large tie groups, whatever broke the tie becomes the signal; risk
#111 records that item-CF does exactly this on the live artifact.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from book_recommender.config import SurfaceConfig
from book_recommender.generators import Candidate, GeneratorResult


@dataclass(frozen=True)
class SourceContribution:
    """What one generator contributed to one fused candidate.

    rec-spec §17 requires all four of these be preserved per candidate:
    the source, its rank, its raw score and its RRF contribution. They are
    kept together rather than as parallel maps so a candidate cannot end up
    with a rank from one generator and a score from another.
    """

    generator: str
    #: 1-based rank within that generator's list.
    rank: int
    #: The generator's own raw score. ``None`` where it has no meaningful
    #: one (the source graph stores edge ranks, not weights).
    raw_score: float | None
    #: ``weight / (rrf_k + rank)`` — this source's share of the total.
    contribution: float
    #: The generator's query strategy, e.g. ``interest:i1``.
    provenance: str


@dataclass(frozen=True)
class FusedCandidate:
    """One book, with every generator that found it.

    Deduplicated by canonical ``book_id`` "without losing provenance"
    (rec-spec §17) — which is why ``sources`` is a tuple rather than the
    single winning generator. ADR-0017: ``candidate_sources`` stays plural
    through the pipeline and into persistence.
    """

    book_id: int
    fusion_score: float
    sources: tuple[SourceContribution, ...] = field(default_factory=tuple)

    @property
    def generators(self) -> tuple[str, ...]:
        """Contributing generator names, in contribution order."""
        return tuple(source.generator for source in self.sources)

    @property
    def agreement(self) -> int:
        """How many independent generators found this book.

        The ranker's second-strongest feature (rec-spec §18). Mechanisms
        that share no input data agreeing on a book is the best evidence V1
        has, since it cannot yet learn from engagement.
        """
        return len(self.sources)

    @property
    def best_rank(self) -> int:
        return min(source.rank for source in self.sources)

    def rank_in(self, generator: str) -> int | None:
        for source in self.sources:
            if source.generator == generator:
                return source.rank
        return None

    def score_in(self, generator: str) -> float | None:
        for source in self.sources:
            if source.generator == generator:
                return source.raw_score
        return None


def fuse(
    results: Sequence[GeneratorResult],
    *,
    surface: SurfaceConfig,
) -> tuple[FusedCandidate, ...]:
    """Merge generator results into one ranked list for ``surface``.

    Generators absent from the surface's quota table, or disabled in it,
    contribute nothing — the surface decides who participates, never the
    generator (rec-spec §17).
    """
    contributions: dict[int, list[SourceContribution]] = {}
    totals: dict[int, float] = {}

    for result in results:
        quota = surface.quota_for(result.generator.value)
        if quota is None or quota.rrf_weight == 0.0:
            continue
        for candidate in result.candidates:
            contribution = quota.rrf_weight / (surface.rrf_k + candidate.rank)
            totals[candidate.book_id] = totals.get(candidate.book_id, 0.0) + contribution
            contributions.setdefault(candidate.book_id, []).append(
                SourceContribution(
                    generator=result.generator.value,
                    rank=candidate.rank,
                    raw_score=candidate.score,
                    contribution=contribution,
                    provenance=candidate.provenance,
                )
            )

    fused = [
        FusedCandidate(
            book_id=book_id,
            fusion_score=total,
            # Strongest contributor first, then generator name, so the
            # source order is itself deterministic and a reader of the
            # diagnostics sees the dominant source immediately.
            sources=tuple(
                sorted(
                    contributions[book_id],
                    key=lambda source: (-source.contribution, source.generator),
                )
            ),
        )
        for book_id, total in totals.items()
    ]

    # Fusion score desc, then agreement desc, then book_id asc. The middle
    # term matters because RRF produces exact ties routinely — two books at
    # the same rank in two equally-weighted generators fuse identically —
    # and consensus is a better tiebreak than catalog insertion order.
    fused.sort(key=lambda item: (-item.fusion_score, -item.agreement, item.book_id))
    return tuple(fused)


def rrf_contribution(weight: float, rank: int, *, rrf_k: int) -> float:
    """ADR-0017's formula for one source, exposed for tests and diagnostics.

    Ranks are 1-based throughout (rec-spec §17: "Use 1-based ranks
    consistently"), and ``rank_all`` in the generator framework is what
    guarantees that on the way in.
    """
    return weight / (rrf_k + rank)


def candidate_book_ids(fused: Sequence[FusedCandidate]) -> tuple[int, ...]:
    return tuple(candidate.book_id for candidate in fused)


def contributions_of(candidate: Candidate, *, weight: float, rrf_k: int) -> float:
    """The RRF contribution one generator candidate would make."""
    return rrf_contribution(weight, candidate.rank, rrf_k=rrf_k)
