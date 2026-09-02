"""Candidate-source coverage and generator agreement (rec-spec §23.3).

This module exists to answer one question that R7 raised and could not
answer: **why do the generators barely overlap?** Only 21 of 602 fused Home
candidates (3.5%) were found by more than one generator, and ADR-0017 chose
weighted RRF precisely because it rewards agreement between independent
mechanisms. A fusion rule whose main virtue never fires is worth knowing
about.

The measurement that makes the raw percentage interpretable is the **chance
baseline**. Five generators each returning ~150 books out of a ~92k catalog
would intersect *somewhere* by pure accident, and it is a much smaller
number than intuition suggests: 150 x 150 / 92,524 is about a quarter of a
book per pair. So "3.5% overlap" is not self-evidently low — it has to be
compared against what independent random draws of the same sizes would
produce, which is what :func:`coverage_report` computes.

The model behind the baseline is deliberately the simplest one that can be
stated in a sentence: every generator draws its candidates uniformly at
random, without replacement, from a shared universe of ``universe_size``
eligible books, independently of the others. Under it, a book's chance of
being drawn by generator *g* is ``|g| / universe_size``, and the expected
number of books drawn by two or more generators follows directly. The model
is wrong in the way every null model is wrong — real generators concentrate
on popular, well-connected books, which should push overlap *up* — and that
is the point: it is a floor to beat, not a prediction.

``lift`` is the ratio of observed agreement to that floor. Lift near 1 means
the generators agree no more than strangers would, which would say the
retrieval families are effectively independent samples and that RRF's
consensus term is decoration. Lift far above 1 means they do agree, and the
absolute percentage is low only because the quotas are shallow slices of a
large catalog — a quota problem rather than an architecture problem.

Nothing here reads a database, a clock or a user identifier: the input is
generator results the pipeline already produced, and the output is counts.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations

from book_recommender.generators import GeneratorResult, GeneratorStatus
from book_recommender.pipeline import FusedCandidate


@dataclass(frozen=True)
class GeneratorCoverage:
    """One generator's contribution to one fused pool."""

    generator: str
    status: str
    #: How many candidates it returned.
    returned: int
    #: How many the surface asked for.
    quota: int
    #: Candidates no other generator found.
    unique: int
    #: Candidates at least one other generator also found.
    shared: int

    @property
    def unique_share(self) -> float:
        return self.unique / self.returned if self.returned else 0.0

    def as_dict(self) -> dict[str, object]:
        return {
            "generator": self.generator,
            "status": self.status,
            "returned": self.returned,
            "quota": self.quota,
            "unique": self.unique,
            "shared": self.shared,
            "unique_share": round(self.unique_share, 4),
        }


@dataclass(frozen=True)
class PairOverlap:
    """Observed against chance-expected agreement for one generator pair."""

    left: str
    right: str
    left_size: int
    right_size: int
    shared: int
    #: ``|left| x |right| / universe`` — the uniform-independent floor.
    expected: float

    @property
    def lift(self) -> float:
        """Observed / expected. ``inf`` when they agree on anything at all
        and the floor rounds to zero, which is a real and readable outcome
        on a catalog this size rather than a division error."""
        if self.expected <= 0.0:
            return math.inf if self.shared else 0.0
        return self.shared / self.expected

    @property
    def jaccard(self) -> float:
        union = self.left_size + self.right_size - self.shared
        return self.shared / union if union else 0.0

    def as_dict(self) -> dict[str, object]:
        lift = self.lift
        return {
            "left": self.left,
            "right": self.right,
            "left_size": self.left_size,
            "right_size": self.right_size,
            "shared": self.shared,
            "expected": round(self.expected, 4),
            "lift": None if math.isinf(lift) else round(lift, 2),
            "jaccard": round(self.jaccard, 5),
        }


@dataclass(frozen=True)
class CoverageReport:
    """Per-generator coverage plus the agreement measurement of risk #119."""

    surface: str
    universe_size: int
    generators: tuple[GeneratorCoverage, ...]
    pairs: tuple[PairOverlap, ...]
    fused_total: int
    multi_source: int
    #: Expected multi-source count under uniform independent draws.
    expected_multi_source: float

    @property
    def multi_source_share(self) -> float:
        return self.multi_source / self.fused_total if self.fused_total else 0.0

    @property
    def agreement_lift(self) -> float:
        """The headline number for risk #119."""
        if self.expected_multi_source <= 0.0:
            return math.inf if self.multi_source else 0.0
        return self.multi_source / self.expected_multi_source

    def as_dict(self) -> dict[str, object]:
        lift = self.agreement_lift
        return {
            "surface": self.surface,
            "universe_size": self.universe_size,
            "fused_total": self.fused_total,
            "multi_source": self.multi_source,
            "multi_source_share": round(self.multi_source_share, 4),
            "expected_multi_source": round(self.expected_multi_source, 3),
            "agreement_lift": None if math.isinf(lift) else round(lift, 1),
            "generators": [entry.as_dict() for entry in self.generators],
            "pairs": [pair.as_dict() for pair in self.pairs],
        }


def expected_multi_source_count(sizes: Sequence[int], *, universe_size: int) -> float:
    """Books expected in two or more of ``sizes`` independent uniform draws.

    Exact under the null model rather than a pairwise approximation: for a
    single book, membership in each generator's list is an independent
    Bernoulli trial with ``p_g = |g| / universe``, so

    .. code-block:: text

        P(>=2) = 1 - P(0) - P(1)
               = 1 - prod(1 - p_g) - sum_g p_g x prod_{h != g} (1 - p_h)

    and the expected count is ``universe x P(>=2)``. Inclusion-exclusion over
    pairs would double-count the books three generators found, which is
    exactly the population the measurement is about.
    """
    if universe_size <= 0:
        return 0.0
    probabilities = [min(size / universe_size, 1.0) for size in sizes if size > 0]
    if len(probabilities) < 2:
        return 0.0

    none_found = 1.0
    for probability in probabilities:
        none_found *= 1.0 - probability

    exactly_one = 0.0
    for index, probability in enumerate(probabilities):
        others = 1.0
        for other_index, other in enumerate(probabilities):
            if other_index != index:
                others *= 1.0 - other
        exactly_one += probability * others

    return universe_size * max(0.0, 1.0 - none_found - exactly_one)


def coverage_report(
    results: Sequence[GeneratorResult],
    *,
    fused: Sequence[FusedCandidate],
    surface: str,
    universe_size: int,
    quotas: dict[str, int] | None = None,
) -> CoverageReport:
    """Coverage and agreement for one surface's generator run.

    ``universe_size`` is the number of books the generators could have
    returned — the eligible catalog, after exclusions. It is supplied rather
    than inferred because no generator result knows it.
    """
    quota_by_generator = quotas or {}
    sets = {
        result.generator.value: set(result.book_ids)
        for result in results
        if result.status is not GeneratorStatus.FAILED
    }

    coverage: list[GeneratorCoverage] = []
    for result in results:
        name = result.generator.value
        own = sets.get(name, set())
        others: set[int] = set()
        for other_name, other in sets.items():
            if other_name != name:
                others |= other
        shared = len(own & others)
        coverage.append(
            GeneratorCoverage(
                generator=name,
                status=str(result.status),
                returned=len(own),
                quota=quota_by_generator.get(name, 0),
                unique=len(own) - shared,
                shared=shared,
            )
        )

    pairs = tuple(
        PairOverlap(
            left=left,
            right=right,
            left_size=len(sets[left]),
            right_size=len(sets[right]),
            shared=len(sets[left] & sets[right]),
            expected=(
                len(sets[left]) * len(sets[right]) / universe_size if universe_size > 0 else 0.0
            ),
        )
        for left, right in combinations(sorted(sets), 2)
    )

    return CoverageReport(
        surface=surface,
        universe_size=universe_size,
        generators=tuple(coverage),
        pairs=pairs,
        fused_total=len(fused),
        multi_source=sum(1 for candidate in fused if candidate.agreement > 1),
        expected_multi_source=expected_multi_source_count(
            [len(books) for books in sets.values()], universe_size=universe_size
        ),
    )


@dataclass(frozen=True)
class RankSaturation:
    """How much of a generator's rank order is decided by its tiebreak.

    Risk #111: item-CF aggregates ``seed_weight x similarity`` over seeds,
    and 10.37% of the artifact's edges have similarity exactly 1.0, so large
    candidate groups land on an identical aggregate and the ``book_id``
    tiebreak orders them. RRF reads only rank, so wherever a tie group is
    large, RRF is consuming catalog insertion order and calling it evidence.

    Measured on the returned list rather than argued from the artifact,
    because what matters is the tie structure of the ranks that actually
    reach fusion.
    """

    generator: str
    returned: int
    distinct_scores: int
    largest_tie_group: int
    #: Candidates sharing their score with at least one other candidate.
    tied_candidates: int
    #: Size of the tie group containing rank 1, where ties cost the most.
    top_tie_group: int

    @property
    def tied_share(self) -> float:
        return self.tied_candidates / self.returned if self.returned else 0.0

    def as_dict(self) -> dict[str, object]:
        return {
            "generator": self.generator,
            "returned": self.returned,
            "distinct_scores": self.distinct_scores,
            "largest_tie_group": self.largest_tie_group,
            "tied_candidates": self.tied_candidates,
            "tied_share": round(self.tied_share, 4),
            "top_tie_group": self.top_tie_group,
        }


def rank_saturation(result: GeneratorResult) -> RankSaturation:
    """Tie structure of one generator's returned ranking."""
    scores = [candidate.score for candidate in result.candidates]
    counts: dict[float, int] = {}
    for score in scores:
        if score is None:
            continue
        counts[score] = counts.get(score, 0) + 1

    tied = sum(count for count in counts.values() if count > 1)
    top_score = scores[0] if scores else None
    return RankSaturation(
        generator=result.generator.value,
        returned=len(result.candidates),
        distinct_scores=len(counts),
        largest_tie_group=max(counts.values(), default=0),
        tied_candidates=tied,
        top_tie_group=0 if top_score is None else counts.get(top_score, 0),
    )
