"""Final-batch diversity and coverage by surface (rec-spec §19, §23.3).

rec-spec §19 asks the reranker to spread a batch across authors, series and
interests without suppressing genuinely relevant items, and rec-spec §23.3
asks for that to be *reported* rather than asserted. This module turns a
finished batch into the numbers those two sections describe.

One deliberate omission: there is no single "diversity score". Author
concentration, genre concentration and source concentration answer different
questions, and a weighted blend of them would hide which one moved. The
report keeps them apart and lets the reader of it decide.

The popularity fields are the check that rec-spec §18's prohibition — "do
not use raw popularity as the dominant personalization score" — holds in
output as well as in the weight table. A batch whose median book sits in the
catalog's top percentile of popularity is a popularity feed regardless of
what produced it.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from book_recommender.artifacts.item_metadata import ItemMetadataTable
from book_recommender.contracts.engine import EngineCandidate
from book_recommender.pipeline.reranking import series_of


@dataclass(frozen=True)
class BatchDiversity:
    """What one finished batch looks like across the axes §19 controls."""

    surface: str
    requested: int
    returned: int
    #: Distinct authors among books the metadata artifact knows.
    distinct_authors: int
    #: Largest number of slots any single author holds.
    top_author_slots: int
    distinct_genres: int
    top_genre_slots: int
    #: Distinct series markers detected in titles.
    distinct_series: int
    top_series_slots: int
    #: How many books each generator produced as their dominant source.
    dominant_sources: Mapping[str, int]
    #: How many books each generator contributed to at all.
    contributing_sources: Mapping[str, int]
    reason_codes: Mapping[str, int]
    #: Books found by more than one generator.
    multi_source: int
    #: Mean/median percentile of the batch in the popularity ranking, where
    #: 1.0 is the most popular book in the catalog. ``None`` without a
    #: popularity artifact.
    mean_popularity_percentile: float | None
    median_popularity_percentile: float | None
    #: Books the metadata artifact had no row for.
    unknown_metadata: int

    @property
    def fill_rate(self) -> float:
        return self.returned / self.requested if self.requested else 0.0

    def as_dict(self) -> dict[str, object]:
        return {
            "surface": self.surface,
            "requested": self.requested,
            "returned": self.returned,
            "fill_rate": round(self.fill_rate, 4),
            "distinct_authors": self.distinct_authors,
            "top_author_slots": self.top_author_slots,
            "distinct_genres": self.distinct_genres,
            "top_genre_slots": self.top_genre_slots,
            "distinct_series": self.distinct_series,
            "top_series_slots": self.top_series_slots,
            "dominant_sources": dict(self.dominant_sources),
            "contributing_sources": dict(self.contributing_sources),
            "reason_codes": dict(self.reason_codes),
            "multi_source": self.multi_source,
            "mean_popularity_percentile": (
                None
                if self.mean_popularity_percentile is None
                else round(self.mean_popularity_percentile, 4)
            ),
            "median_popularity_percentile": (
                None
                if self.median_popularity_percentile is None
                else round(self.median_popularity_percentile, 4)
            ),
            "unknown_metadata": self.unknown_metadata,
        }


def batch_diversity(
    candidates: Sequence[EngineCandidate],
    *,
    surface: str,
    requested: int,
    metadata: ItemMetadataTable | None = None,
    popularity: Mapping[int, float] | None = None,
) -> BatchDiversity:
    """Describe one finished batch.

    Missing artifacts degrade the report rather than failing it, matching
    how the pipeline itself behaves (rec-spec §27): without metadata there
    are no author/genre/series numbers, without popularity no percentiles.
    """
    authors: Counter[str] = Counter()
    genres: Counter[str] = Counter()
    series: Counter[str] = Counter()
    unknown = 0

    if metadata is not None:
        for candidate in candidates:
            row = metadata.get(candidate.book_id)
            if row is None:
                unknown += 1
                continue
            if row.author:
                authors[row.author] += 1
            if row.genre:
                genres[row.genre] += 1
            name = series_of(row.title)
            if name:
                series[name] += 1

    dominant: Counter[str] = Counter()
    contributing: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    multi_source = 0
    for candidate in candidates:
        sources = tuple(candidate.candidate_sources)
        if sources:
            dominant[sources[0]] += 1
            for source in sources:
                contributing[source] += 1
            if len(sources) > 1:
                multi_source += 1
        reasons[str(candidate.reason_code)] += 1

    mean_percentile, median_percentile = _popularity_percentiles(candidates, popularity)

    return BatchDiversity(
        surface=surface,
        requested=requested,
        returned=len(candidates),
        distinct_authors=len(authors),
        top_author_slots=max(authors.values(), default=0),
        distinct_genres=len(genres),
        top_genre_slots=max(genres.values(), default=0),
        distinct_series=len(series),
        top_series_slots=max(series.values(), default=0),
        dominant_sources=dict(dominant.most_common()),
        contributing_sources=dict(contributing.most_common()),
        reason_codes=dict(reasons.most_common()),
        multi_source=multi_source,
        mean_popularity_percentile=mean_percentile,
        median_popularity_percentile=median_percentile,
        unknown_metadata=unknown,
    )


def _popularity_percentiles(
    candidates: Sequence[EngineCandidate], popularity: Mapping[int, float] | None
) -> tuple[float | None, float | None]:
    """Where the batch sits in the popularity distribution.

    Percentile of the *score*, not of the rank: the popularity artifact is a
    Bayesian-shrunk score whose distribution is heavily skewed, and a rank
    percentile would report a book barely above the median as if it were
    typical of the head.
    """
    if not popularity or not candidates:
        return (None, None)

    ordered = sorted(popularity.values())
    total = len(ordered)
    percentiles: list[float] = []
    for candidate in candidates:
        score = popularity.get(candidate.book_id)
        if score is None:
            continue
        # Fraction of the catalog this book is at least as popular as.
        low, high = 0, total
        while low < high:
            middle = (low + high) // 2
            if ordered[middle] <= score:
                low = middle + 1
            else:
                high = middle
        percentiles.append(low / total)

    if not percentiles:
        return (None, None)
    ordered_percentiles = sorted(percentiles)
    middle_index = len(ordered_percentiles) // 2
    median = (
        ordered_percentiles[middle_index]
        if len(ordered_percentiles) % 2
        else (ordered_percentiles[middle_index - 1] + ordered_percentiles[middle_index]) / 2
    )
    return (sum(percentiles) / len(percentiles), median)
