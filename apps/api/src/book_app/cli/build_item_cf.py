"""CLI: build the item-item collaborative-filtering artifact
(rec-spec §10, §23.1).

    uv run --project apps/api --group training python -m book_app.cli.build_item_cf [options]

or via ``make build-item-cf``. Needs the ``training`` group
(``make setup-training``).

Same shape as ``build_als``: evaluate the candidate similarity variants on
the same per-user holdout, ship the winner rebuilt on the full dataset.
rec-spec §10 asks specifically for "a simple cosine baseline and a
popularity-aware TF-IDF/BM25 nearest-neighbour variant if practical", with
the V1 default selected "from offline metrics plus coverage/popularity
behavior" — so the report carries catalog coverage and a Gini coefficient
next to the accuracy numbers, and they are meant to be read together. A
variant that wins on NDCG by recommending the same bestsellers to everyone
is not the better model.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from book_recommender.artifacts import (
    LocalArtifactStorage,
    write_artifact,
    write_item_cf_neighbors,
)
from book_recommender.artifacts.item_cf import NEIGHBORS_FILENAME
from book_recommender.config import (
    EVALUATION_K_VALUES,
    HISTORICAL_TRANSFORM_V1,
    HOLDOUT_DEFAULT,
    ITEM_CF,
    ITEM_CF_DEFAULT,
    ITEM_CF_SWEEP,
    SELECTION_K,
    ItemCfConfig,
)
from sqlalchemy.orm import Session, sessionmaker

from book_app.core.config import get_settings
from book_app.core.database import create_db_engine, create_session_factory
from book_app.core.logging import configure_logging, get_logger
from book_app.modules.books import repository as books_repository
from book_app.modules.recommendations.artifact_build import (
    ArtifactBuildReport,
    new_model_version,
    register_model_version,
)
from book_app.modules.recommendations.artifact_paths import (
    read_catalog_snapshot,
    resolve_artifact_root,
)
from book_app.modules.recommendations.cf_evaluation import (
    EvaluationResult,
    build_holdout,
    evaluate_rankings,
    write_evaluation_report,
)
from book_app.modules.recommendations.cf_training import (
    build_user_item_matrix,
    rank_from_neighbors,
    train_item_neighbors,
)
from book_app.modules.recommendations.interaction_transform import (
    build_dataset,
    catalog_items_in_index_order,
    read_interactions,
)

logger = get_logger("book_app.cli.build_item_cf")

# Anchored at the repo root, not the CWD: `make build-als` runs from
# apps/api while a plain `python -m` runs from the root, and a bare
# relative path would silently mean different files (same reasoning as
# cli/import_catalog.py and modules/recommendations/artifact_paths.py).
_REPO_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_INTERACTIONS_PATH = _REPO_ROOT / "data" / "processed" / "interactions.parquet"
EVALUATION_DEPTH = max(EVALUATION_K_VALUES)
#: Users scored per variant. The neighbour scan is per-seed rather than one
#: matrix product, so evaluating all ~40k holdout readers would dominate the
#: build; a fixed, deterministic prefix is enough to separate two variants.
DEFAULT_EVALUATION_USERS = 3000


def run_build(
    session_factory: sessionmaker[Session],
    *,
    artifact_root: Path,
    interactions_path: Path,
    configs: tuple[ItemCfConfig, ...] = (ITEM_CF_DEFAULT,),
    include_neutral: bool = False,
    evaluation_users: int = DEFAULT_EVALUATION_USERS,
    dry_run: bool = False,
    evaluation_root: Path | None = None,
) -> ArtifactBuildReport:
    transform = HISTORICAL_TRANSFORM_V1.with_neutral(include_neutral)

    with session_factory() as session:
        catalog = read_catalog_snapshot(session)
        catalog_version = books_repository.get_catalog_version(session)
        model_version = new_model_version()

        frame = read_interactions(interactions_path)
        dataset = build_dataset(frame, catalog, transform)
        stats: dict[str, int | str] = dict(dataset.report.as_stats())
        stats["transform_version"] = dataset.transform_version

        if not len(dataset):
            return ArtifactBuildReport(
                model_name=ITEM_CF.name,
                model_version=model_version,
                catalog_version=catalog_version,
                item_count=0,
                dry_run=dry_run,
                stats=stats,
            )

        split = build_holdout(dataset.user_indices, dataset.item_indices, HOLDOUT_DEFAULT)
        train_matrix = build_user_item_matrix(dataset, row_mask=split.train_mask)
        evaluated_users = sorted(split.held_out_items)[:evaluation_users]
        stats["holdout_users"] = split.evaluated_user_count
        stats["evaluated_users"] = len(evaluated_users)

        results: list[EvaluationResult] = []
        for config in configs:
            indptr, indices, scores = train_item_neighbors(train_matrix, config)
            rankings = rank_from_neighbors(
                indptr,
                indices,
                scores,
                train_matrix,
                evaluated_users,
                count=EVALUATION_DEPTH,
                item_count=dataset.item_count,
            )
            result = evaluate_rankings(
                config.label,
                rankings,
                split.held_out_items,
                k_values=EVALUATION_K_VALUES,
                item_count=dataset.item_count,
                config={
                    "similarity": config.similarity,
                    "top_k": config.top_k,
                    "transform": dataset.transform_version,
                },
            )
            results.append(result)
            logger.info("item_cf_config_evaluated", label=config.label, **result.metrics)

        best_index = max(range(len(results)), key=lambda i: results[i].primary(SELECTION_K))
        best_config = configs[best_index]
        stats["selected_config"] = best_config.label
        stats[f"selected_ndcg@{SELECTION_K}"] = f"{results[best_index].primary(SELECTION_K):.4f}"
        stats["selected_coverage"] = f"{results[best_index].catalog_coverage:.4f}"
        stats["selected_gini"] = f"{results[best_index].popularity_gini:.4f}"

        full_matrix = build_user_item_matrix(dataset)
        indptr, indices, scores = train_item_neighbors(full_matrix, best_config)
        stats["edges"] = len(indices)
        stats["items_with_neighbors"] = sum(
            1 for i in range(len(indptr) - 1) if indptr[i + 1] > indptr[i]
        )

        preview = [
            {"label": result.label, **{k: round(v, 4) for k, v in result.metrics.items()}}
            for result in results
        ]

        if dry_run:
            return ArtifactBuildReport(
                model_name=ITEM_CF.name,
                model_version=model_version,
                catalog_version=catalog_version,
                item_count=dataset.item_count,
                dry_run=True,
                stats=stats,
                preview=preview,
            )

        written = write_artifact(
            LocalArtifactStorage(artifact_root),
            ITEM_CF,
            model_version=model_version,
            catalog_version=catalog_version,
            items=catalog_items_in_index_order(catalog),
            payloads={
                NEIGHBORS_FILENAME: lambda path: write_item_cf_neighbors(
                    path, indptr=indptr, neighbor_indices=indices, scores=scores
                )
            },
            config={
                "similarity": best_config.similarity,
                "top_k": best_config.top_k,
                "bm25_k1": best_config.bm25_k1,
                "bm25_b": best_config.bm25_b,
                "selected_by": f"ndcg@{SELECTION_K}",
            },
            training_transform_version=dataset.transform_version,
        )
        register_model_version(session, ITEM_CF, written)
        session.commit()

        if evaluation_root is not None:
            report_path = write_evaluation_report(
                evaluation_root,
                model_name=ITEM_CF.name,
                model_version=model_version,
                results=results,
                selected=best_config.label,
                context={
                    "catalog_version": catalog_version,
                    "transform_version": dataset.transform_version,
                    "holdout": HOLDOUT_DEFAULT.__dict__,
                    "evaluated_users": len(evaluated_users),
                    "dataset": dataset.report.as_stats(),
                },
            )
            stats["evaluation_report"] = str(report_path)

        return ArtifactBuildReport(
            model_name=ITEM_CF.name,
            model_version=model_version,
            catalog_version=catalog_version,
            item_count=dataset.item_count,
            dry_run=False,
            checksums=written.checksums,
            stats=stats,
            preview=preview,
            stale_files=written.stale_files,
        )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the item-item CF artifact.")
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="Compare cosine and BM25 variants and ship the winner (rec-spec §10)",
    )
    parser.add_argument("--similarity", choices=("cosine", "bm25"))
    parser.add_argument("--top-k", type=int, default=ITEM_CF_DEFAULT.top_k)
    parser.add_argument("--with-neutral", action="store_true")
    parser.add_argument("--evaluation-users", type=int, default=DEFAULT_EVALUATION_USERS)
    parser.add_argument("--interactions", type=Path, default=DEFAULT_INTERACTIONS_PATH)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = get_settings()
    configure_logging(settings)

    if args.sweep:
        configs = ITEM_CF_SWEEP
    elif args.similarity:
        configs = (ItemCfConfig(similarity=args.similarity, top_k=args.top_k),)
    else:
        configs = (ITEM_CF_DEFAULT,)

    artifact_root = resolve_artifact_root(settings.artifact_storage_local_path)
    engine = create_db_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        report = run_build(
            session_factory,
            artifact_root=artifact_root,
            interactions_path=args.interactions,
            configs=configs,
            include_neutral=args.with_neutral,
            evaluation_users=args.evaluation_users,
            dry_run=args.dry_run,
            evaluation_root=artifact_root / "evaluation",
        )
    finally:
        engine.dispose()

    print(report.summary_line())
    for line in report.warning_lines():
        print(line)
    for key, value in report.stats.items():
        print(f"  {key}: {value}")
    for row in report.preview:
        print(f"  {row}")

    logger.info("build_item_cf_completed", **report.stats, dry_run=report.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
