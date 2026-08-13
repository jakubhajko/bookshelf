"""CLI: train and export the ALS collaborative-filtering artifact
(rec-spec §9.1, §23.1).

    uv run --project apps/api --group training python -m book_app.cli.build_als [options]

or via ``make build-als``. Requires the ``training`` dependency group, which
``make setup`` deliberately does not install (ADR-0021) — run
``make setup-training`` once first.

The shipped model is chosen, not asserted. rec-spec §9.1 says to "sweep a
small reasonable config grid ... rather than hard-coding one unexplained
choice", and §23.1 says to compare them on a documented per-user holdout.
So the flow is:

1. resolve historical interactions onto the live catalog (shared transform);
2. hold out a random fraction of each active reader's books — random, because
   the data has no timestamps and a temporal split would be a fiction;
3. train each candidate config on the remainder and score it;
4. **retrain the winner on the full dataset** — the holdout exists to rank
   configurations, and shipping a model that never saw 20% of the evidence
   would waste it;
5. write the artifact and a separate evaluation report.

Only item factors reach the artifact. The historical user factors are used
for evaluation and dropped: they describe Book-Crossing readers, who are not
application users (rec-spec §7.2), so serving them would put unjoinable
personal data in every API worker.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from book_recommender.artifacts import LocalArtifactStorage, write_artifact, write_item_factors
from book_recommender.artifacts.als import ITEM_FACTORS_FILENAME
from book_recommender.config import (
    ALS,
    ALS_DEFAULT,
    ALS_SWEEP,
    EVALUATION_K_VALUES,
    HISTORICAL_TRANSFORM_V1,
    HOLDOUT_DEFAULT,
    SELECTION_K,
    AlsConfig,
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
    rank_for_users,
    train_als,
)
from book_app.modules.recommendations.interaction_transform import (
    build_dataset,
    catalog_items_in_index_order,
    read_interactions,
)

logger = get_logger("book_app.cli.build_als")

# Anchored at the repo root, not the CWD: `make build-als` runs from
# apps/api while a plain `python -m` runs from the root, and a bare
# relative path would silently mean different files (same reasoning as
# cli/import_catalog.py and modules/recommendations/artifact_paths.py).
_REPO_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_INTERACTIONS_PATH = _REPO_ROOT / "data" / "processed" / "interactions.parquet"
#: Ranking depth used during evaluation — the largest cutoff plus headroom.
EVALUATION_DEPTH = max(EVALUATION_K_VALUES)
PREVIEW_SIZE = 5


def run_build(
    session_factory: sessionmaker[Session],
    *,
    artifact_root: Path,
    interactions_path: Path,
    configs: tuple[AlsConfig, ...] = (ALS_DEFAULT,),
    include_neutral: bool = False,
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
                model_name=ALS.name,
                model_version=model_version,
                catalog_version=catalog_version,
                item_count=0,
                dry_run=dry_run,
                stats=stats,
            )

        split = build_holdout(dataset.user_indices, dataset.item_indices, HOLDOUT_DEFAULT)
        stats["holdout_users"] = split.evaluated_user_count
        stats["train_rows"] = split.train_row_count

        train_matrix = build_user_item_matrix(dataset, row_mask=split.train_mask)
        evaluated_users = sorted(split.held_out_items)

        results: list[EvaluationResult] = []
        for config in configs:
            trained = train_als(train_matrix, config)
            rankings = rank_for_users(
                trained, train_matrix, evaluated_users, count=EVALUATION_DEPTH
            )
            result = evaluate_rankings(
                config.label,
                rankings,
                split.held_out_items,
                k_values=EVALUATION_K_VALUES,
                item_count=dataset.item_count,
                config={
                    "factors": config.factors,
                    "regularization": config.regularization,
                    "iterations": config.iterations,
                    "transform": dataset.transform_version,
                },
            )
            results.append(result)
            logger.info("als_config_evaluated", label=config.label, **result.metrics)

        best_index = max(range(len(results)), key=lambda i: results[i].primary(SELECTION_K))
        best_config = configs[best_index]
        best_result = results[best_index]
        stats["selected_config"] = best_config.label
        stats[f"selected_ndcg@{SELECTION_K}"] = f"{best_result.primary(SELECTION_K):.4f}"

        # The holdout picked the configuration; the shipped model gets all
        # the evidence (see the module docstring).
        full_matrix = build_user_item_matrix(dataset)
        final = train_als(full_matrix, best_config)
        stats["factors"] = final.factor_count
        stats["item_factor_rows"] = int(final.item_factors.shape[0])

        preview = [
            {"label": result.label, **{k: round(v, 4) for k, v in result.metrics.items()}}
            for result in results[:PREVIEW_SIZE]
        ]

        if dry_run:
            return ArtifactBuildReport(
                model_name=ALS.name,
                model_version=model_version,
                catalog_version=catalog_version,
                item_count=dataset.item_count,
                dry_run=True,
                stats=stats,
                preview=preview,
            )

        item_factors = final.item_factors
        written = write_artifact(
            LocalArtifactStorage(artifact_root),
            ALS,
            model_version=model_version,
            catalog_version=catalog_version,
            items=catalog_items_in_index_order(catalog),
            payloads={ITEM_FACTORS_FILENAME: lambda path: write_item_factors(path, item_factors)},
            config={
                "factors": best_config.factors,
                "regularization": best_config.regularization,
                "iterations": best_config.iterations,
                "random_state": best_config.random_state,
                "selected_by": f"ndcg@{SELECTION_K}",
            },
            training_transform_version=dataset.transform_version,
        )
        register_model_version(session, ALS, written)
        session.commit()

        if evaluation_root is not None:
            report_path = write_evaluation_report(
                evaluation_root,
                model_name=ALS.name,
                model_version=model_version,
                results=results,
                selected=best_config.label,
                context={
                    "catalog_version": catalog_version,
                    "transform_version": dataset.transform_version,
                    "holdout": HOLDOUT_DEFAULT.__dict__,
                    "dataset": dataset.report.as_stats(),
                },
            )
            stats["evaluation_report"] = str(report_path)

        return ArtifactBuildReport(
            model_name=ALS.name,
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
    parser = argparse.ArgumentParser(description="Train and export the ALS artifact.")
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="Evaluate the full config grid and ship the winner (rec-spec §9.1)",
    )
    parser.add_argument("--factors", type=int, help="Train a single config with this factor count")
    parser.add_argument("--regularization", type=float, default=ALS_DEFAULT.regularization)
    parser.add_argument("--iterations", type=int, default=ALS_DEFAULT.iterations)
    parser.add_argument(
        "--with-neutral",
        action="store_true",
        help="Include historical rating 6 as weak positive evidence (rec-spec §7.2)",
    )
    parser.add_argument("--interactions", type=Path, default=DEFAULT_INTERACTIONS_PATH)
    parser.add_argument("--dry-run", action="store_true", help="Train and evaluate without writing")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = get_settings()
    configure_logging(settings)

    if args.sweep:
        configs = ALS_SWEEP
    elif args.factors:
        configs = (
            AlsConfig(
                factors=args.factors,
                regularization=args.regularization,
                iterations=args.iterations,
            ),
        )
    else:
        configs = (ALS_DEFAULT,)

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

    logger.info("build_als_completed", **report.stats, dry_run=report.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
