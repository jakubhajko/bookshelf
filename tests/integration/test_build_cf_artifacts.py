"""ALS and item-CF builders against real PostgreSQL (rec-spec §9, §10).

Skipped without the ``training`` dependency group (ADR-0021):

    uv run --project apps/api --group training pytest tests/integration -q

What these cover that the unit tests cannot: the builders write artifacts
the *runtime loaders* accept, resolved against a real catalog snapshot — the
writer/reader contract ADR-0014 exists to keep from drifting.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from book_app.modules.recommendations.artifact_paths import read_catalog_snapshot
from book_recommender.artifacts import (
    LocalArtifactStorage,
    load_als_artifact,
    load_item_cf_artifact,
)
from book_recommender.config import ALS, ITEM_CF, SELECTION_K, AlsConfig, ItemCfConfig
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

pytest.importorskip("implicit", reason="training dependency group not installed")
pytest.importorskip("scipy", reason="training dependency group not installed")

from book_app.cli import build_als, build_item_cf

ITEM_COUNT = 30


@pytest.fixture
def catalog_books(test_engine: Engine) -> list[int]:
    """A catalog big enough that the loaders' 10%-unresolved threshold and
    the holdout's minimum-interactions rule both behave normally."""
    ids: list[int] = []
    with test_engine.begin() as conn:
        for index in range(ITEM_COUNT):
            ids.append(
                conn.execute(
                    text(
                        "INSERT INTO books (work_id, title, catalog_status) "
                        "VALUES (:work_id, :title, 'ACTIVE') RETURNING id"
                    ),
                    {"work_id": f"w-{index}", "title": f"Book {index}"},
                ).scalar_one()
            )
    return ids


@pytest.fixture
def interactions(tmp_path: Path) -> Path:
    """Two disjoint reading communities, written as a real parquet file so
    the builders exercise their actual read path."""
    rows: list[dict[str, object]] = []
    for user in range(40):
        items = range(10) if user < 20 else range(15, 25)
        for item in items:
            rows.append(
                {
                    "user_id": user,
                    "work_id": f"w-{item}",
                    "rating": 8,
                    "is_explicit": True,
                }
            )
    frame = pd.DataFrame(rows).astype(
        {
            "user_id": "int32",
            "work_id": "string",
            "rating": "int8",
            "is_explicit": "bool",
        }
    )
    path = tmp_path / "interactions.parquet"
    frame.to_parquet(path, index=False)
    return path


# --- ALS --------------------------------------------------------------------


def test_als_artifact_round_trips_through_the_runtime_loader(
    test_session_factory: sessionmaker[Session],
    catalog_books: list[int],
    interactions: Path,
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "artifacts"

    report = build_als.run_build(
        test_session_factory,
        artifact_root=artifact_root,
        interactions_path=interactions,
        configs=(AlsConfig(factors=8, regularization=0.05, iterations=10),),
    )

    assert report.item_count == ITEM_COUNT
    assert report.stats["rows_used"] == 400

    with test_session_factory() as session:
        catalog = read_catalog_snapshot(session)
    artifact = load_als_artifact(LocalArtifactStorage(artifact_root), catalog=catalog)

    assert artifact.item_count == ITEM_COUNT
    assert artifact.factor_count == 8
    assert artifact.bundle.manifest.training_transform_version == (
        "bx-positive-only-v1+no-neutral"
    )


def test_a_folded_in_user_gets_candidates_from_their_own_community(
    test_session_factory: sessionmaker[Session],
    catalog_books: list[int],
    interactions: Path,
    tmp_path: Path,
) -> None:
    """The end-to-end claim of rec-spec §9.2: a live user who never appeared
    in training gets sensible candidates from fixed item factors alone."""
    artifact_root = tmp_path / "artifacts"
    build_als.run_build(
        test_session_factory,
        artifact_root=artifact_root,
        interactions_path=interactions,
        configs=(AlsConfig(factors=16, regularization=0.01, iterations=25),),
    )

    with test_session_factory() as session:
        catalog = read_catalog_snapshot(session)
    artifact = load_als_artifact(LocalArtifactStorage(artifact_root), catalog=catalog)

    # A brand-new reader who likes three books from the first community.
    liked = [catalog_books[0], catalog_books[1], catalog_books[2]]
    factor = artifact.fold_in([(book_id, 3.0) for book_id in liked])
    assert factor is not None

    candidates = artifact.top_candidates(
        factor, count=5, excluded_book_ids=frozenset(liked)
    )
    community = set(catalog_books[0:10])
    recommended = {book_id for book_id, _ in candidates}

    assert recommended
    assert recommended <= community


def test_als_registers_an_active_model_version(
    test_session_factory: sessionmaker[Session],
    test_engine: Engine,
    catalog_books: list[int],
    interactions: Path,
    tmp_path: Path,
) -> None:
    report = build_als.run_build(
        test_session_factory,
        artifact_root=tmp_path / "artifacts",
        interactions_path=interactions,
        configs=(AlsConfig(factors=8, regularization=0.05, iterations=5),),
    )

    with test_engine.connect() as conn:
        row = conn.execute(
            text("SELECT model_name, status, model_version FROM model_versions")
        ).one()
    assert row.model_name == ALS.name
    assert row.status == "ACTIVE"
    assert row.model_version == report.model_version


def test_als_dry_run_writes_nothing(
    test_session_factory: sessionmaker[Session],
    test_engine: Engine,
    catalog_books: list[int],
    interactions: Path,
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "artifacts"

    report = build_als.run_build(
        test_session_factory,
        artifact_root=artifact_root,
        interactions_path=interactions,
        configs=(AlsConfig(factors=8, regularization=0.05, iterations=5),),
        dry_run=True,
    )

    assert report.dry_run is True
    assert not artifact_root.exists()
    with test_engine.connect() as conn:
        assert (
            conn.execute(text("SELECT count(*) FROM model_versions")).scalar_one() == 0
        )


def test_the_sweep_selects_a_config_and_records_why(
    test_session_factory: sessionmaker[Session],
    catalog_books: list[int],
    interactions: Path,
    tmp_path: Path,
) -> None:
    """rec-spec §9.1 wants the shipped config chosen by evaluation, and the
    artifact to say which one and on what basis."""
    artifact_root = tmp_path / "artifacts"
    configs = (
        AlsConfig(factors=8, regularization=0.05, iterations=10),
        AlsConfig(factors=16, regularization=0.05, iterations=10),
    )

    report = build_als.run_build(
        test_session_factory,
        artifact_root=artifact_root,
        interactions_path=interactions,
        configs=configs,
        evaluation_root=artifact_root / "evaluation",
    )

    assert report.stats["selected_config"] in {config.label for config in configs}
    assert len(report.preview) == 2

    manifest = LocalArtifactStorage(artifact_root).load_manifest(ALS.directory)
    assert manifest.config["selected_by"] == f"ndcg@{SELECTION_K}"
    assert manifest.config["factors"] in {8, 16}

    reports = list((artifact_root / "evaluation").glob("als-*.json"))
    assert len(reports) == 1
    assert (artifact_root / "evaluation" / f"{reports[0].stem}.txt").is_file()


def test_historical_users_never_reach_the_artifact(
    test_session_factory: sessionmaker[Session],
    catalog_books: list[int],
    interactions: Path,
    tmp_path: Path,
) -> None:
    """rec-spec §7.2: historical Book-Crossing readers are not application
    users. Only item factors are persisted — no user vectors, no user ids."""
    artifact_root = tmp_path / "artifacts"
    build_als.run_build(
        test_session_factory,
        artifact_root=artifact_root,
        interactions_path=interactions,
        configs=(AlsConfig(factors=8, regularization=0.05, iterations=5),),
    )

    files = {path.name for path in (artifact_root / ALS.directory).iterdir()}
    assert files == {"manifest.json", "mapping.npz", "item_factors.npy"}

    manifest_text = (artifact_root / ALS.directory / "manifest.json").read_text()
    assert "user" not in manifest_text.lower()


# --- Item-item CF -----------------------------------------------------------


def test_item_cf_artifact_round_trips_through_the_runtime_loader(
    test_session_factory: sessionmaker[Session],
    catalog_books: list[int],
    interactions: Path,
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "artifacts"

    report = build_item_cf.run_build(
        test_session_factory,
        artifact_root=artifact_root,
        interactions_path=interactions,
        configs=(ItemCfConfig(similarity="cosine", top_k=5),),
    )

    assert report.item_count == ITEM_COUNT

    with test_session_factory() as session:
        catalog = read_catalog_snapshot(session)
    artifact = load_item_cf_artifact(
        LocalArtifactStorage(artifact_root), catalog=catalog
    )

    assert artifact.similarity == "cosine"
    assert artifact.top_k == 5
    # Neighbours of a first-community book stay inside that community.
    neighbours = {n.book_id for n in artifact.neighbors(catalog_books[0])}
    assert neighbours
    assert neighbours <= set(catalog_books[0:10])


def test_item_cf_seeds_produce_community_candidates(
    test_session_factory: sessionmaker[Session],
    catalog_books: list[int],
    interactions: Path,
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "artifacts"
    build_item_cf.run_build(
        test_session_factory,
        artifact_root=artifact_root,
        interactions_path=interactions,
        configs=(ItemCfConfig(similarity="bm25", top_k=10),),
    )

    with test_session_factory() as session:
        catalog = read_catalog_snapshot(session)
    artifact = load_item_cf_artifact(
        LocalArtifactStorage(artifact_root), catalog=catalog
    )

    seeds = [(catalog_books[15], 1.0), (catalog_books[16], 1.0)]
    candidates = artifact.candidates_from_seeds(seeds, count=5)

    assert candidates
    assert {book_id for book_id, _ in candidates} <= set(catalog_books[15:25])


def test_both_cf_families_share_one_item_index_space(
    test_session_factory: sessionmaker[Session],
    catalog_books: list[int],
    interactions: Path,
    tmp_path: Path,
) -> None:
    """ADR-0014's shared item space, checked across two independently-built
    families: the same ``model_item_index`` must name the same book."""
    artifact_root = tmp_path / "artifacts"
    build_als.run_build(
        test_session_factory,
        artifact_root=artifact_root,
        interactions_path=interactions,
        configs=(AlsConfig(factors=8, regularization=0.05, iterations=5),),
    )
    build_item_cf.run_build(
        test_session_factory,
        artifact_root=artifact_root,
        interactions_path=interactions,
        configs=(ItemCfConfig(similarity="cosine", top_k=5),),
    )

    storage = LocalArtifactStorage(artifact_root)
    with test_session_factory() as session:
        catalog = read_catalog_snapshot(session)

    als = load_als_artifact(storage, catalog=catalog)
    item_cf = load_item_cf_artifact(storage, catalog=catalog)

    assert als.book_ids.tolist() == list(item_cf._row_by_book_id)
    assert storage.load_manifest(ALS.directory).item_count == (
        storage.load_manifest(ITEM_CF.directory).item_count
    )


def test_rebuilding_produces_identical_payloads(
    test_session_factory: sessionmaker[Session],
    catalog_books: list[int],
    interactions: Path,
    tmp_path: Path,
) -> None:
    """rec-spec §28 and the phase's own "neighbour artifacts deterministic
    for fixed config"."""
    config = (ItemCfConfig(similarity="bm25", top_k=5),)

    first = build_item_cf.run_build(
        test_session_factory,
        artifact_root=tmp_path / "a",
        interactions_path=interactions,
        configs=config,
    )
    second = build_item_cf.run_build(
        test_session_factory,
        artifact_root=tmp_path / "b",
        interactions_path=interactions,
        configs=config,
    )

    assert first.checksums == second.checksums


def test_als_rebuild_is_deterministic(
    test_session_factory: sessionmaker[Session],
    catalog_books: list[int],
    interactions: Path,
    tmp_path: Path,
) -> None:
    config = (AlsConfig(factors=8, regularization=0.05, iterations=5, random_state=3),)

    first = build_als.run_build(
        test_session_factory,
        artifact_root=tmp_path / "a",
        interactions_path=interactions,
        configs=config,
    )
    second = build_als.run_build(
        test_session_factory,
        artifact_root=tmp_path / "b",
        interactions_path=interactions,
        configs=config,
    )

    assert first.checksums == second.checksums
