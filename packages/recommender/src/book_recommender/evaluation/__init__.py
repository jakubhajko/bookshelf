"""Offline evaluation and diagnostics over pipeline output (rec-spec §23).

Separate from the pipeline rather than inside it, because these are
whole-run measurements — agreement between generators, diversity of a
finished batch, duplicate density in the catalog — and none of them belongs
on the request path. Everything here is pure: it reads generator results,
finished batches and artifacts, and returns counts. No database, no clock,
no I/O, exactly like the generators it measures.

The application's ``evaluate_recommender`` CLI is the caller that has a
database and can therefore build real reader contexts; it drives the real
serving pipeline and hands the output to these functions, so what gets
measured is what gets served (CLAUDE.md: "inspection tooling must call the
same implementation used by serving").
"""

from book_recommender.evaluation.coverage import (
    CoverageReport,
    GeneratorCoverage,
    PairOverlap,
    RankSaturation,
    coverage_report,
    expected_multi_source_count,
    rank_saturation,
)
from book_recommender.evaluation.diversity import BatchDiversity, batch_diversity
from book_recommender.evaluation.duplicates import (
    EDITION,
    EXACT,
    SUBTITLE,
    TIERS,
    DuplicateGroup,
    DuplicateReport,
    TierResult,
    duplicate_report,
    tier_key,
)

__all__ = [
    "EDITION",
    "EXACT",
    "SUBTITLE",
    "TIERS",
    "BatchDiversity",
    "CoverageReport",
    "DuplicateGroup",
    "DuplicateReport",
    "GeneratorCoverage",
    "PairOverlap",
    "RankSaturation",
    "TierResult",
    "batch_diversity",
    "coverage_report",
    "duplicate_report",
    "expected_multi_source_count",
    "rank_saturation",
    "tier_key",
]
