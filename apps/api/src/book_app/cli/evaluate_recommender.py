"""CLI: evaluate the assembled recommendation pipeline (rec-spec §23.3).

    make evaluate-recommender USERNAME=Jakub
    make evaluate-recommender USERNAME=Jakub ARGS="--section duplicates"
    make evaluate-recommender USERNAME=Jakub ARGS="--json"

rec-spec §23.3 asks for candidate-source coverage, final diversity, cold-start
behaviour and fallback frequency to be *reported* rather than asserted, and the
implementation plan's Phase 9 adds latency and fill rate to the list. This is
that report.

**It drives the real engine.** The pipeline is built by the same
``build_pipeline_engine`` serving uses, contexts come from the same
``build_user_context``, and eligibility from the same ``eligibility`` module.
The one thing it uses that a request does not is
``PipelineRecommendationEngine.run``, which returns the intermediate state of
the stages ``recommend`` itself calls — so what is measured here is what is
served, not a reconstruction of it (CLAUDE.md).

Sections, each independently selectable with ``--section``:

``surfaces``
    Per-surface generator coverage, the agreement measurement of risk #119,
    item-CF rank saturation (risk #111), final-batch diversity and stage
    latency.
``depth``
    Overlap as a function of quota depth. The direct test of the first
    explanation for #119: if the generators are shallow slices of a large
    catalog rather than genuinely disjoint, agreement rises with depth.
``cold-start``
    Six synthetic readers, from no evidence at all to eight taste seeds, in
    coherent and scattered variants, checking rec-spec §22's ladder fires.
``interests``
    ``merge_threshold`` swept against real and synthetic readers: how many
    interests form, and how much evidence reaches none of them (risks #105,
    #110).
``sensitivity``
    Every surface weight halved in turn, to show which knobs move the first
    screen and which are inert (risk #120).
``degradation``
    Every artifact family removed in turn, checking rec-spec §27's promise
    that a missing artifact costs its generator and nothing else.
``duplicates``
    Near-duplicate work density in the catalog (risk #117).
``latency``
    Repeat runs per surface, reported as a distribution rather than one
    number.

Needs no training dependencies: it reads artifacts.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from book_recommender.artifacts import (
    CatalogSnapshot,
    LocalArtifactStorage,
    PopularityArtifact,
    load_popularity_artifact,
)
from book_recommender.config import INTEREST_PROFILE_DEFAULT, SURFACES, SurfaceConfig
from book_recommender.contracts.context import (
    HomeContext,
    ShelfContext,
    SimilarBooksContext,
    SurfaceContext,
    TasteSeedSnapshot,
    UserContext,
)
from book_recommender.contracts.engine import RecommendationEngineRequest
from book_recommender.engines.pipeline import PipelineRecommendationEngine
from book_recommender.evaluation import (
    batch_diversity,
    coverage_report,
    duplicate_report,
    rank_saturation,
)
from book_recommender.exceptions import IncompatibleArtifactError
from book_recommender.profiling import build_semantic_profile
from sqlalchemy import select
from sqlalchemy.orm import Session

from book_app.core.config import get_settings
from book_app.core.database import create_db_engine, create_session_factory
from book_app.core.logging import configure_logging
from book_app.modules.books import repository as books_repository
from book_app.modules.recommendations import eligibility
from book_app.modules.recommendations.artifact_paths import (
    build_artifact_storage,
    read_catalog_snapshot,
)
from book_app.modules.recommendations.context_builder import build_user_context
from book_app.modules.recommendations.wiring import build_pipeline_engine
from book_app.modules.shelves import repository as shelves_repository
from book_app.modules.shelves.models import Shelf
from book_app.modules.users.models import User

SECTIONS: tuple[str, ...] = (
    "surfaces",
    "depth",
    "cold-start",
    "interests",
    "sensitivity",
    "degradation",
    "duplicates",
    "latency",
)

#: rec-spec §24's batch size, matching what the service requests.
BATCH_SIZE = 60
#: Quota multipliers for the depth sweep. 1x is the shipped configuration.
DEPTH_FACTORS: tuple[float, ...] = (0.5, 1.0, 2.0, 4.0)
LATENCY_RUNS = 5


@dataclass(frozen=True)
class SurfaceCase:
    """One surface, ready to run: its context and its exclusions."""

    label: str
    surface: str
    context: SurfaceContext
    user_context: UserContext
    exclusions: frozenset[int]


def _engine_request(
    case: SurfaceCase, *, catalog_version: str, count: int = BATCH_SIZE
) -> RecommendationEngineRequest:
    return RecommendationEngineRequest(
        request_id=uuid4(),
        user_context=case.user_context,
        surface_context=case.context,
        requested_count=count,
        hard_exclusions=case.exclusions,
        session_exclusions=frozenset(),
        catalog_version=catalog_version,
    )


def build_cases(
    session: Session,
    *,
    user_id: UUID,
    source_book_id: int | None,
    shelf_id: UUID | None,
) -> list[SurfaceCase]:
    """A real reader's three surfaces, using the service's own eligibility."""
    user_context = build_user_context(session, user_id=user_id)
    cases = [
        SurfaceCase(
            label="home",
            surface="home",
            context=HomeContext(),
            user_context=user_context,
            exclusions=eligibility.home_exclusions(user_context),
        )
    ]

    shelf = _pick_shelf(session, user_id=user_id, shelf_id=shelf_id)
    if shelf is not None:
        book_ids = frozenset(shelves_repository.get_book_ids_in_shelf(session, shelf_id=shelf.id))
        cases.append(
            SurfaceCase(
                label=f"shelf:{shelf.name}",
                surface="shelf",
                context=ShelfContext(
                    shelf_id=shelf.id,
                    shelf_name=shelf.name,
                    shelf_description=shelf.description,
                    shelf_book_ids=book_ids,
                ),
                user_context=user_context,
                exclusions=eligibility.shelf_exclusions(user_context, shelf_book_ids=book_ids),
            )
        )

    source = _pick_source_book(user_context, source_book_id)
    if source is not None:
        cases.append(
            SurfaceCase(
                label=f"similar:{source}",
                surface="similar",
                context=SimilarBooksContext(source_book_id=source),
                user_context=user_context,
                exclusions=eligibility.similar_exclusions(user_context, source_book_id=source),
            )
        )
    return cases


def _pick_shelf(session: Session, *, user_id: UUID, shelf_id: UUID | None) -> Shelf | None:
    if shelf_id is not None:
        return shelves_repository.get_owned(session, user_id=user_id, shelf_id=shelf_id)
    # The fullest shelf, because a shelf of one book measures the fallback
    # ladder rather than the shelf surface.
    shelves = session.scalars(select(Shelf).where(Shelf.user_id == user_id)).all()
    best: Shelf | None = None
    best_count = 0
    for shelf in shelves:
        count = len(shelves_repository.get_book_ids_in_shelf(session, shelf_id=shelf.id))
        if count > best_count:
            best, best_count = shelf, count
    return best if best_count else None


def _pick_source_book(user_context: UserContext, source_book_id: int | None) -> int | None:
    if source_book_id is not None:
        return source_book_id
    strongest = sorted(user_context.ratings, key=lambda r: (-r.rating_value, r.book_id))
    if strongest:
        return strongest[0].book_id
    if user_context.saved_books:
        return min(saved.book_id for saved in user_context.saved_books)
    return None


# --- sections ---------------------------------------------------------------


def surfaces_section(
    engine: PipelineRecommendationEngine,
    cases: Sequence[SurfaceCase],
    *,
    catalog_version: str,
    universe_size: int,
    popularity: PopularityArtifact | None,
) -> dict[str, Any]:
    """Coverage, agreement, saturation, diversity and timing per surface."""
    metadata = engine.dependencies.metadata
    popularity_map = None if popularity is None else dict(popularity.ranking)

    entries: list[dict[str, Any]] = []
    for case in cases:
        request = _engine_request(case, catalog_version=catalog_version)
        trace = engine.run(request)
        result = engine.recommend(request)

        coverage = coverage_report(
            trace.generator_results,
            fused=trace.fused,
            surface=case.label,
            universe_size=max(universe_size - len(case.exclusions), 1),
            quotas=trace.quotas,
        )
        entries.append(
            {
                "case": case.label,
                "surface": case.surface,
                "excluded_books": len(case.exclusions),
                "coverage": coverage.as_dict(),
                "saturation": [
                    rank_saturation(generator_result).as_dict()
                    for generator_result in trace.generator_results
                    if generator_result.candidates
                ],
                "diversity": batch_diversity(
                    result.candidates,
                    surface=case.label,
                    requested=BATCH_SIZE,
                    metadata=metadata,
                    popularity=popularity_map,
                ).as_dict(),
                "stage_ms": dict(trace.stage_ms),
                "top": _top_books(result.candidates, metadata, limit=8),
            }
        )
    return {"surfaces": entries}


def _top_books(candidates: Sequence[Any], metadata: Any, *, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for position, candidate in enumerate(candidates[:limit], start=1):
        row = None if metadata is None else metadata.get(candidate.book_id)
        rows.append(
            {
                "position": position,
                "book_id": candidate.book_id,
                "title": "" if row is None else row.title,
                "author": "" if row is None else row.author,
                "score": round(candidate.score, 4),
                "sources": list(candidate.candidate_sources),
                "reason": str(candidate.reason_code),
            }
        )
    return rows


def depth_section(
    engine: PipelineRecommendationEngine,
    cases: Sequence[SurfaceCase],
    *,
    catalog_version: str,
    universe_size: int,
) -> dict[str, Any]:
    """Agreement as a function of how deep each generator retrieves.

    The decisive test for risk #119. Three explanations were possible: the
    quotas are too shallow for the lists to intersect, the generators are
    genuinely complementary, or item-CF's noise means its candidates should
    rarely be confirmed. Scaling every quota and re-measuring separates the
    first from the other two — shallow slices of a big catalog produce
    agreement that grows superlinearly with depth, genuinely disjoint
    retrieval universes do not.
    """
    entries: list[dict[str, Any]] = []
    for case in cases:
        points: list[dict[str, Any]] = []
        for factor in DEPTH_FACTORS:
            scaled = _scale_surface(SURFACES[case.surface], factor)
            scaled_engine = engine.with_surfaces({case.surface: scaled})
            trace = scaled_engine.run(_engine_request(case, catalog_version=catalog_version))
            coverage = coverage_report(
                trace.generator_results,
                fused=trace.fused,
                surface=case.label,
                universe_size=max(universe_size - len(case.exclusions), 1),
                quotas=trace.quotas,
            )
            points.append(
                {
                    "factor": factor,
                    "retrieved": sum(len(r.candidates) for r in trace.generator_results),
                    **{
                        key: coverage.as_dict()[key]
                        for key in (
                            "fused_total",
                            "multi_source",
                            "multi_source_share",
                            "expected_multi_source",
                            "agreement_lift",
                        )
                    },
                }
            )
        entries.append({"case": case.label, "points": points})
    return {"depth": entries}


def _scale_surface(surface: SurfaceConfig, factor: float) -> SurfaceConfig:
    return replace(
        surface,
        quotas=tuple(
            replace(quota, count=max(1, int(round(quota.count * factor))))
            if quota.enabled
            else quota
            for quota in surface.quotas
        ),
    )


def cold_start_section(
    engine: PipelineRecommendationEngine,
    *,
    catalog_version: str,
    reference: UserContext,
    scattered_book_ids: Sequence[int],
    coherent_book_ids: Sequence[int],
) -> dict[str, Any]:
    """rec-spec §22's ladder, from an empty reader upward.

    Each rung is the same reader with strictly less evidence, so a
    difference between rungs is a difference the pipeline made rather than a
    difference between two people.

    **Two kinds of seeded reader, because onboarding is search-driven.** The
    reader picks books by searching for them (``routes/Onboarding.tsx``), so
    a realistic seed set is *coherent* — someone who searches "dune" and
    "tolkien" selects books that resemble each other. The scattered rungs
    take arbitrary catalog rows instead, which is the worst case for
    interest clustering rather than the typical one. Reporting both is what
    makes ``profile_strategy`` here mean something: risks #105, #110 and
    #128 are all about whether clustering fires for a real reader, and one
    seed set cannot answer that.
    """
    empty = _empty_context(reference.user_id)
    rungs: list[tuple[str, UserContext]] = [
        ("no-evidence", empty),
        ("coherent x1", _with_seeds(empty, coherent_book_ids[:1])),
        ("coherent x3", _with_seeds(empty, coherent_book_ids[:3])),
        ("coherent x8", _with_seeds(empty, coherent_book_ids[:8])),
        ("scattered x3", _with_seeds(empty, scattered_book_ids[:3])),
        ("scattered x8", _with_seeds(empty, scattered_book_ids[:8])),
    ]

    entries: list[dict[str, Any]] = []
    for label, context in rungs:
        case = SurfaceCase(
            label=label,
            surface="home",
            context=HomeContext(),
            user_context=context,
            exclusions=eligibility.home_exclusions(context),
        )
        request = _engine_request(case, catalog_version=catalog_version)
        trace = engine.run(request)
        result = engine.recommend(request)
        entries.append(
            {
                "rung": label,
                "taste_seeds": len(context.taste_seeds),
                "returned": len(result.candidates),
                "fill_rate": round(len(result.candidates) / BATCH_SIZE, 3),
                "profile_strategy": result.diagnostics.get("profile_strategy"),
                "interests": result.diagnostics.get("interests"),
                "generators": {
                    generator_result.generator.value: {
                        "status": str(generator_result.status),
                        "candidates": len(generator_result.candidates),
                    }
                    for generator_result in trace.generator_results
                },
                "reason_codes": _counted(str(c.reason_code) for c in result.candidates),
                "dominant_sources": _counted(
                    c.candidate_sources[0] for c in result.candidates if c.candidate_sources
                ),
            }
        )
    return {"cold_start": entries}


def coherent_seed_books(
    engine: PipelineRecommendationEngine,
    popularity: PopularityArtifact | None,
    *,
    count: int = 8,
) -> tuple[int, ...]:
    """A plausible onboarding selection: a well-known book and its neighbours.

    The most popular book the artifact knows, plus its nearest semantic
    neighbours — which is roughly what a reader produces by searching for
    something they like and picking several of the results.
    """
    embeddings = engine.dependencies.embeddings
    if embeddings is None or popularity is None or not popularity.ranking:
        return ()
    # `ranking` is most-popular-first by construction.
    anchor = popularity.ranking[0][0]
    vector = embeddings.vector_for(anchor)
    if vector is None:
        return ()
    neighbours = embeddings.search(vector, count=count, excluded_book_ids=frozenset({anchor}))
    return (anchor, *[book_id for book_id, _ in neighbours])[:count]


def _empty_context(user_id: UUID) -> UserContext:
    return UserContext(
        user_id=user_id,
        ratings=(),
        saved_book_ids=frozenset(),
        saved_books=(),
        shelf_ids=(),
        not_interested_book_ids=frozenset(),
        recent_interactions=(),
        shelf_summaries=(),
        taste_seeds=(),
        profile_version="evaluation",
    )


def _with_seeds(context: UserContext, book_ids: Sequence[int]) -> UserContext:
    now = datetime.now(UTC)
    return context.model_copy(
        update={
            "taste_seeds": tuple(
                TasteSeedSnapshot(book_id=book_id, source="onboarding", selected_at=now)
                for book_id in book_ids
            )
        }
    )


def _counted(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return dict(sorted(counts.items(), key=lambda item: -item[1]))


#: Thresholds swept for the interest-clustering measurement. The shipped
#: default (0.55) sits in the middle so the sweep shows both directions.
MERGE_THRESHOLDS: tuple[float, ...] = (0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70)

#: Perturbation applied to one weight at a time in the sensitivity section.
SENSITIVITY_FACTOR = 0.5
#: How deep into the batch the sensitivity comparison looks. The first
#: screen is what a weight change is actually felt through.
SENSITIVITY_DEPTH = 20


def sensitivity_section(
    engine: PipelineRecommendationEngine,
    cases: Sequence[SurfaceCase],
    *,
    catalog_version: str,
) -> dict[str, Any]:
    """How much each tunable actually moves the batch (risk #120).

    rec-spec §18 and ADR-0017 both gate a *learned* ranker on engagement
    labels that do not exist yet, and the same gate applies to fitting these
    weights: there is nothing to fit them against. What can be established
    without labels is **influence** — halve a weight, and see how much of
    the first screen changes.

    That is worth having for two reasons. A weight that moves nothing is not
    a tuning opportunity, it is dead configuration, and a weight that moves
    everything is where a careless edit does damage. Neither is visible from
    reading the numbers, and both are cheap to measure now that a full
    pipeline run costs tens of milliseconds.

    It is emphatically **not** a quality measurement. It says which knobs are
    connected, not which settings are right.
    """
    entries: list[dict[str, Any]] = []
    for case in cases:
        surface = SURFACES[case.surface]
        request = _engine_request(case, catalog_version=catalog_version)
        baseline = [entry.book_id for entry in engine.run(request).final]

        knobs: list[dict[str, Any]] = []
        for quota in surface.quotas:
            if not quota.enabled or quota.rrf_weight == 0.0:
                continue
            perturbed = replace(
                surface,
                quotas=tuple(
                    replace(other, rrf_weight=other.rrf_weight * SENSITIVITY_FACTOR)
                    if other.generator == quota.generator
                    else other
                    for other in surface.quotas
                ),
            )
            knobs.append(
                _sensitivity_point(
                    engine,
                    request,
                    surface_name=case.surface,
                    perturbed=perturbed,
                    knob=f"rrf:{quota.generator}",
                    baseline=baseline,
                )
            )

        for field_name in (
            "fusion",
            "agreement",
            "semantic_relevance",
            "collaborative_relevance",
            "popularity_prior",
            "evidence_affinity",
            "surface_coherence",
            "negative_evidence",
        ):
            current = getattr(surface.ranking, field_name)
            perturbed = replace(
                surface,
                ranking=replace(surface.ranking, **{field_name: current * SENSITIVITY_FACTOR}),
            )
            knobs.append(
                _sensitivity_point(
                    engine,
                    request,
                    surface_name=case.surface,
                    perturbed=perturbed,
                    knob=f"rank:{field_name}",
                    baseline=baseline,
                )
            )

        for field_name in (
            "author_penalty",
            "series_penalty",
            "interest_concentration_penalty",
            "source_concentration_penalty",
            "near_duplicate_penalty",
        ):
            current = getattr(surface.rerank, field_name)
            perturbed = replace(
                surface,
                rerank=replace(surface.rerank, **{field_name: current * SENSITIVITY_FACTOR}),
            )
            knobs.append(
                _sensitivity_point(
                    engine,
                    request,
                    surface_name=case.surface,
                    perturbed=perturbed,
                    knob=f"rerank:{field_name}",
                    baseline=baseline,
                )
            )

        knobs.sort(key=lambda knob: (-knob["changed_at_20"], -knob["mean_shift"]))
        entries.append({"case": case.label, "knobs": knobs})
    return {"sensitivity": entries}


def _sensitivity_point(
    engine: PipelineRecommendationEngine,
    request: RecommendationEngineRequest,
    *,
    surface_name: str,
    perturbed: SurfaceConfig,
    knob: str,
    baseline: Sequence[int],
) -> dict[str, Any]:
    result = engine.with_surfaces({surface_name: perturbed}).run(request)
    changed = [entry.book_id for entry in result.final]

    head_before = list(baseline[:SENSITIVITY_DEPTH])
    head_after = changed[:SENSITIVITY_DEPTH]
    positions = {book_id: index for index, book_id in enumerate(changed)}
    shifts = [
        abs(positions[book_id] - index)
        for index, book_id in enumerate(head_before)
        if book_id in positions
    ]
    return {
        "knob": knob,
        "changed_at_20": len(set(head_before) - set(head_after)),
        "changed_overall": len(set(baseline) - set(changed)),
        "mean_shift": round(sum(shifts) / len(shifts), 2) if shifts else 0.0,
        "identical": changed == list(baseline),
    }


def interests_section(
    engine: PipelineRecommendationEngine,
    *,
    contexts: Sequence[tuple[str, UserContext]],
) -> dict[str, Any]:
    """``merge_threshold`` against what it actually produces (risks #105, #110).

    R5 shipped 0.55 reasoned from the shape of the vector space — unrelated
    normalized Qwen3 books sit around 0.2-0.35, same-series above 0.7 — and
    nothing has ever swept it against a real reader. Two numbers matter and
    neither was known:

    - **singletons**, the evidence books that reach no interest at all.
      rec-spec §12.2's ``min_cluster_size = 2`` drops them, so a reader with
      isolated corners of taste gets no semantic retrieval from those books
      (risk #110).
    - **strategy**, which says whether clustering fired at all or the
      fallback ladder caught it.

    The sweep runs the same ``build_semantic_profile`` serving uses, with
    only the config varied — CLAUDE.md's rule that inspection reuses the
    serving implementation applies as much to a parameter sweep as to a
    single inspection.
    """
    embeddings = engine.dependencies.embeddings
    if embeddings is None:
        return {"interests": {"error": "content artifact unavailable"}}

    entries: list[dict[str, Any]] = []
    for label, context in contexts:
        points: list[dict[str, Any]] = []
        for threshold in MERGE_THRESHOLDS:
            profile = build_semantic_profile(
                context,
                embeddings,
                config=replace(INTEREST_PROFILE_DEFAULT, merge_threshold=threshold),
            )
            clusters = profile.interests.clusters
            clustered_books = {
                book_id for cluster in clusters for book_id in cluster.member_book_ids
            }
            evidence = profile.interests.evidence_count
            points.append(
                {
                    "merge_threshold": threshold,
                    "strategy": str(profile.interests.strategy),
                    "interests": len(clusters),
                    "evidence": evidence,
                    "clustered_books": len(clustered_books),
                    "singletons": max(evidence - len(clustered_books), 0),
                    "largest_interest": max((c.member_count for c in clusters), default=0),
                    "unembedded": len(profile.interests.unembedded_book_ids),
                }
            )
        entries.append({"reader": label, "points": points})
    return {"interests": entries}


def degradation_section(
    build: Callable[[frozenset[str]], PipelineRecommendationEngine],
    cases: Sequence[SurfaceCase],
    *,
    catalog_version: str,
    families: Sequence[str],
) -> dict[str, Any]:
    """rec-spec §27: one missing artifact costs its generator, not the batch.

    Simulated by rebuilding the engine with that family withheld, rather
    than by moving files: the failure being modelled is "the loader returned
    None", which is what an absent, stale or corrupt artifact all reduce to
    in ``wiring._load_optional``.
    """
    entries: list[dict[str, Any]] = []
    for family in ("none", *families):
        withheld = frozenset() if family == "none" else frozenset({family})
        engine = build(withheld)
        for case in cases:
            request = _engine_request(case, catalog_version=catalog_version)
            result = engine.recommend(request)
            generators = result.diagnostics.get("generators", {})
            entries.append(
                {
                    "withheld": family,
                    "case": case.label,
                    "returned": len(result.candidates),
                    "fill_rate": round(len(result.candidates) / BATCH_SIZE, 3),
                    "empty_batch": not result.candidates,
                    "generator_statuses": {
                        name: value["status"] for name, value in generators.items()
                    },
                    "fused_candidates": result.diagnostics.get("fused_candidates"),
                }
            )
    return {"degradation": entries}


def duplicates_section(engine: PipelineRecommendationEngine) -> dict[str, Any]:
    metadata = engine.dependencies.metadata
    if metadata is None:
        return {"duplicates": {"error": "item-metadata artifact unavailable"}}
    return {"duplicates": duplicate_report(metadata).as_dict()}


def latency_section(
    engine: PipelineRecommendationEngine,
    cases: Sequence[SurfaceCase],
    *,
    catalog_version: str,
    runs: int = LATENCY_RUNS,
) -> dict[str, Any]:
    """Repeated timing per surface.

    Reported as min/median/max rather than a single number, because the
    first run of a memory-mapped artifact pays page faults the rest do not
    (risk #125) and a mean would hide exactly that.
    """
    entries: list[dict[str, Any]] = []
    for case in cases:
        totals: list[float] = []
        stages: dict[str, list[float]] = {}
        for _ in range(runs):
            started = time.perf_counter()
            trace = engine.run(_engine_request(case, catalog_version=catalog_version))
            totals.append((time.perf_counter() - started) * 1000.0)
            for name, value in trace.stage_ms.items():
                stages.setdefault(name, []).append(value)
        entries.append(
            {
                "case": case.label,
                "runs": runs,
                "first_ms": round(totals[0], 2),
                "min_ms": round(min(totals), 2),
                "median_ms": round(statistics.median(totals), 2),
                "max_ms": round(max(totals), 2),
                "stage_median_ms": {
                    name: round(statistics.median(values), 2) for name, values in stages.items()
                },
            }
        )
    return {"latency": entries}


# --- rendering --------------------------------------------------------------


def _render(report: dict[str, Any]) -> str:
    lines: list[str] = [f"recommender evaluation — {report['model_version']}", ""]

    for entry in report.get("surfaces", []):
        coverage = entry["coverage"]
        lift = coverage["agreement_lift"]
        lines += [
            f"[{entry['case']}]  surface={entry['surface']}  excluded={entry['excluded_books']}",
            "  generators   "
            + "  ".join(
                f"{g['generator']}:{g['returned']}/{g['quota']}({g['status']})"
                for g in coverage["generators"]
            ),
            f"  fused        {coverage['fused_total']}  "
            f"multi-source {coverage['multi_source']} "
            f"({coverage['multi_source_share']:.1%})  "
            f"expected-by-chance {coverage['expected_multi_source']}  "
            f"lift {'inf' if lift is None else f'{lift}x'}",
            "  pairwise     "
            + "  ".join(
                f"{p['left'][:4]}/{p['right'][:4]}:{p['shared']}"
                for p in coverage["pairs"]
                if p["shared"]
            ),
        ]
        diversity = entry["diversity"]
        lines += [
            f"  batch        {diversity['returned']}/{diversity['requested']} "
            f"(fill {diversity['fill_rate']:.0%})  "
            f"{diversity['distinct_authors']} authors "
            f"(max {diversity['top_author_slots']})  "
            f"{diversity['distinct_genres']} genres "
            f"(max {diversity['top_genre_slots']})",
            f"  popularity   mean p{_percent(diversity['mean_popularity_percentile'])} "
            f"median p{_percent(diversity['median_popularity_percentile'])}",
            f"  sources      {diversity['dominant_sources']}",
            f"  reasons      {diversity['reason_codes']}",
            f"  stage_ms     {entry['stage_ms']}",
        ]
        for saturation in entry["saturation"]:
            if saturation["tied_share"] > 0.0:
                lines.append(
                    f"  saturation   {saturation['generator']}: "
                    f"{saturation['distinct_scores']} distinct scores over "
                    f"{saturation['returned']} candidates, "
                    f"{saturation['tied_share']:.0%} tied, "
                    f"largest group {saturation['largest_tie_group']}, "
                    f"rank-1 group {saturation['top_tie_group']}"
                )
        for book in entry["top"][:6]:
            lines.append(
                f"    {book['position']:>2}. {book['title'][:44]!r} — {book['author'][:22]}"
                f"  {'+'.join(book['sources'])}  {book['score']}"
            )
        lines.append("")

    for entry in report.get("depth", []):
        lines.append(f"[depth {entry['case']}]")
        for point in entry["points"]:
            lift = point["agreement_lift"]
            lines.append(
                f"  x{point['factor']:<4} retrieved {point['retrieved']:>5}  "
                f"fused {point['fused_total']:>5}  "
                f"multi-source {point['multi_source']:>4} "
                f"({point['multi_source_share']:.1%})  "
                f"chance {point['expected_multi_source']:>6}  "
                f"lift {'inf' if lift is None else f'{lift}x'}"
            )
        lines.append("")

    for entry in report.get("cold_start", []):
        lines += [
            f"[cold-start {entry['rung']}]  seeds={entry['taste_seeds']}  "
            f"returned={entry['returned']} (fill {entry['fill_rate']:.0%})  "
            f"strategy={entry['profile_strategy']}  interests={entry['interests']}",
            f"  generators {entry['generators']}",
            f"  reasons    {entry['reason_codes']}",
            "",
        ]

    for entry in report.get("sensitivity", []):
        lines.append(f"[sensitivity {entry['case']}]  each knob halved, top-20 compared")
        for knob in entry["knobs"]:
            flag = "  (no effect)" if knob["identical"] else ""
            lines.append(
                f"  {knob['knob']:<34} changed@20 {knob['changed_at_20']:>2}  "
                f"changed@60 {knob['changed_overall']:>2}  "
                f"mean shift {knob['mean_shift']:>5}{flag}"
            )
        lines.append("")

    interests = report.get("interests")
    if isinstance(interests, list):
        for entry in interests:
            lines.append(f"[interests {entry['reader']}]")
            for point in entry["points"]:
                lines.append(
                    f"  merge {point['merge_threshold']:.2f}  "
                    f"{point['strategy']:<18} interests {point['interests']:>2}  "
                    f"evidence {point['evidence']:>3}  "
                    f"clustered {point['clustered_books']:>3}  "
                    f"singletons {point['singletons']:>3}  "
                    f"largest {point['largest_interest']:>3}  "
                    f"unembedded {point['unembedded']}"
                )
            lines.append("")

    degradation = report.get("degradation", [])
    if degradation:
        lines.append("[degradation]  withheld artifact -> batch")
        for entry in degradation:
            lines.append(
                f"  {entry['withheld']:<18} {entry['case']:<24} "
                f"returned {entry['returned']:>3} (fill {entry['fill_rate']:.0%})  "
                f"fused {entry['fused_candidates']}  "
                f"{entry['generator_statuses']}"
            )
        lines.append("")

    duplicates = report.get("duplicates")
    if isinstance(duplicates, dict) and "tiers" in duplicates:
        lines.append(
            f"[duplicates]  catalog {duplicates['catalog_size']}  "
            f"unkeyable {duplicates['unkeyable']}"
        )
        for tier in duplicates["tiers"]:
            lines.append(
                f"  {tier['tier']:<9} groups {tier['groups']:>5}  "
                f"books {tier['books']:>6}  redundant {tier['redundant']:>6} "
                f"({tier['redundant_share']:.2%})  largest {tier['largest_group']}"
            )
            for group in tier["samples"][:4]:
                lines.append(f"      {group['titles']} — {group['author']}")
        lines.append("")

    for entry in report.get("latency", []):
        lines.append(
            f"[latency {entry['case']}]  first {entry['first_ms']}ms  "
            f"min {entry['min_ms']}ms  median {entry['median_ms']}ms  "
            f"max {entry['max_ms']}ms  {entry['stage_median_ms']}"
        )

    return "\n".join(lines)


def _percent(value: float | None) -> str:
    return "?" if value is None else f"{value * 100:.1f}"


# --- entry point ------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the recommendation pipeline.")
    parser.add_argument("--username", required=True)
    parser.add_argument(
        "--section",
        action="append",
        choices=SECTIONS,
        help="Run only these sections (repeatable). Default: all.",
    )
    parser.add_argument("--source-book-id", type=int, default=None)
    parser.add_argument("--shelf-id", type=str, default=None)
    parser.add_argument("--latency-runs", type=int, default=LATENCY_RUNS)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def _withholding_builder(
    storage: LocalArtifactStorage,
    catalog: CatalogSnapshot,
    popularity: PopularityArtifact | None,
) -> Callable[[frozenset[str]], PipelineRecommendationEngine]:
    """Rebuild the serving engine with some artifact families removed."""

    def build(withheld: frozenset[str]) -> PipelineRecommendationEngine:
        return build_pipeline_engine(
            storage,
            catalog,
            None if "popularity" in withheld else popularity,
            withheld_families=withheld,
        )

    return build


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    sections = frozenset(args.section or SECTIONS)
    settings = get_settings()
    # The report is this command's output; the logs are not. With --json they
    # must not share a stream.
    configure_logging(settings, stream=sys.stderr if args.json else None)

    db_engine = create_db_engine(settings)
    session_factory = create_session_factory(db_engine)
    storage = build_artifact_storage(settings)

    try:
        with session_factory() as session:
            user = session.scalar(select(User).where(User.username == args.username))
            if user is None:
                print(f"error: no user named {args.username!r}", file=sys.stderr)
                return 1
            catalog = read_catalog_snapshot(session)
            catalog_version = books_repository.get_catalog_version(session)
            # The eligible universe the generators drew from: active books
            # in the catalog identity table, which is exactly the set every
            # artifact resolved against.
            universe_size = len(catalog)
            cases = build_cases(
                session,
                user_id=user.id,
                source_book_id=args.source_book_id,
                shelf_id=UUID(args.shelf_id) if args.shelf_id else None,
            )
            popular_book_ids = books_repository.get_active_book_ids(session, limit=64)

        try:
            popularity = load_popularity_artifact(storage, catalog=catalog)
        except IncompatibleArtifactError as exc:
            print(f"warning: popularity artifact unavailable ({exc})", file=sys.stderr)
            popularity = None

        started = time.perf_counter()
        engine = build_pipeline_engine(storage, catalog, popularity)
        load_ms = (time.perf_counter() - started) * 1000.0

        report: dict[str, Any] = {
            "username": args.username,
            "catalog_version": catalog_version,
            "catalog_size": universe_size,
            "model_version": engine.dependencies.resolved_model_version(),
            "artifact_versions": dict(engine.dependencies.artifact_versions),
            "artifact_load_ms": round(load_ms, 1),
        }

        if "surfaces" in sections:
            report |= surfaces_section(
                engine,
                cases,
                catalog_version=catalog_version,
                universe_size=universe_size,
                popularity=popularity,
            )
        if "depth" in sections:
            report |= depth_section(
                engine, cases, catalog_version=catalog_version, universe_size=universe_size
            )
        if "cold-start" in sections:
            report |= cold_start_section(
                engine,
                catalog_version=catalog_version,
                reference=cases[0].user_context,
                scattered_book_ids=popular_book_ids,
                coherent_book_ids=coherent_seed_books(engine, popularity),
            )
        if "interests" in sections:
            empty = _empty_context(cases[0].user_context.user_id)
            coherent = coherent_seed_books(engine, popularity)
            report |= interests_section(
                engine,
                contexts=[
                    (args.username, cases[0].user_context),
                    ("synthetic coherent x8", _with_seeds(empty, coherent)),
                    ("synthetic scattered x8", _with_seeds(empty, popular_book_ids[:8])),
                ],
            )
        if "sensitivity" in sections:
            report |= sensitivity_section(engine, cases, catalog_version=catalog_version)
        if "degradation" in sections:
            report |= degradation_section(
                _withholding_builder(storage, catalog, popularity),
                cases,
                catalog_version=catalog_version,
                families=(
                    "content",
                    "item_metadata",
                    "als",
                    "item_cf",
                    "source_similarity",
                    "popularity",
                ),
            )
        if "duplicates" in sections:
            report |= duplicates_section(engine)
        if "latency" in sections:
            report |= latency_section(
                engine, cases, catalog_version=catalog_version, runs=args.latency_runs
            )
    finally:
        db_engine.dispose()

    print(json.dumps(report, indent=2) if args.json else _render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
