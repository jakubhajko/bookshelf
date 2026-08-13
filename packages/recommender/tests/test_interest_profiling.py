"""Interest clustering, shelf profiles and inspectable summaries
(rec-spec §12, §13).

The fallback ladder is where the value is: most real readers have very
little evidence, and the failure mode to avoid is confidently presenting
cluster structure that was invented from three books.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pytest

from book_recommender.config import InterestProfileConfig
from book_recommender.profiling import (
    BookDescriptor,
    EvidenceItem,
    ProfileStrategy,
    average_linkage_clusters,
    build_interest_profile,
    build_label,
    build_shelf_profiles,
    cosine_similarity_matrix,
    medoid_index,
    query_vector_for,
    summarize_profile,
    weighted_centroid,
)

CONFIG = InterestProfileConfig()


class FakeEmbeddings:
    """Two orthogonal taste axes, so "different interests" is a fact about
    the fixture rather than a hope: books 1-3 load on axis 0, books 11-13 on
    axis 1, and the two groups have cosine similarity ~0."""

    def __init__(self, vectors: dict[int, list[float]] | None = None) -> None:
        self._vectors = vectors or {
            1: [1.0, 0.0, 0.0],
            2: [0.98, 0.20, 0.0],
            3: [0.96, 0.28, 0.0],
            11: [0.0, 1.0, 0.0],
            12: [0.20, 0.98, 0.0],
            13: [0.0, 0.96, 0.28],
        }

    def vectors_for(self, book_ids: Sequence[int]) -> tuple[np.ndarray, list[int]]:
        rows, resolved = [], []
        for book_id in book_ids:
            vector = self._vectors.get(book_id)
            if vector is None:
                continue
            unit = np.asarray(vector, dtype=np.float32)
            rows.append(unit / np.linalg.norm(unit))
            resolved.append(book_id)
        if not rows:
            return np.empty((0, 3), dtype=np.float32), []
        return np.vstack(rows).astype(np.float32), resolved


def _evidence(*pairs: tuple[int, float], source: str = "rating") -> list[EvidenceItem]:
    return [EvidenceItem(book_id=b, weight=w, source=source) for b, w in pairs]


# --- Clustering primitives --------------------------------------------------


def test_clustering_merges_only_above_the_threshold() -> None:
    similarity = np.array([[1.0, 0.9, 0.1], [0.9, 1.0, 0.1], [0.1, 0.1, 1.0]])

    assert average_linkage_clusters(similarity, threshold=0.5) == ((0, 1), (2,))
    assert average_linkage_clusters(similarity, threshold=0.95) == ((0,), (1,), (2,))
    assert average_linkage_clusters(similarity, threshold=0.05) == ((0, 1, 2),)


def test_clustering_does_not_force_a_fixed_k() -> None:
    """rec-spec §12.2: the number of interests is an outcome, not an input."""
    three_groups = np.eye(6)
    for a, b in ((0, 1), (2, 3), (4, 5)):
        three_groups[a, b] = three_groups[b, a] = 0.9

    assert len(average_linkage_clusters(three_groups, threshold=0.5)) == 3


def test_clustering_is_deterministic_and_ordered() -> None:
    rng = np.random.default_rng(0)
    matrix = rng.normal(size=(12, 5))
    similarity = cosine_similarity_matrix(matrix)

    first = average_linkage_clusters(similarity, threshold=0.3)
    second = average_linkage_clusters(similarity, threshold=0.3)

    assert first == second
    assert all(list(group) == sorted(group) for group in first)
    assert [group[0] for group in first] == sorted(group[0] for group in first)


def test_average_linkage_uses_pre_merge_sizes() -> None:
    """A merged cluster's similarity to an outsider is the size-weighted mean
    of its parts'. Using the post-merge size for both halves silently turns
    this into something that is not average linkage."""
    similarity = np.array(
        [
            [1.0, 0.95, 0.10],
            [0.95, 1.0, 0.50],
            [0.10, 0.50, 1.0],
        ]
    )
    # 0 and 1 merge first. Their average link to 2 is (0.10 + 0.50)/2 = 0.30.
    assert average_linkage_clusters(similarity, threshold=0.31) == ((0, 1), (2,))
    assert average_linkage_clusters(similarity, threshold=0.29) == ((0, 1, 2),)


def test_weighted_centroid_is_normalized_and_weighted() -> None:
    vectors = np.array([[1.0, 0.0], [0.0, 1.0]])

    balanced = weighted_centroid(vectors, np.array([1.0, 1.0]))
    skewed = weighted_centroid(vectors, np.array([9.0, 1.0]))

    assert float(np.linalg.norm(balanced)) == pytest.approx(1.0)
    assert balanced[0] == pytest.approx(balanced[1])
    assert skewed[0] > skewed[1]


def test_medoid_is_the_most_central_member() -> None:
    similarity = np.array([[1.0, 0.9, 0.9], [0.9, 1.0, 0.2], [0.9, 0.2, 1.0]])

    assert medoid_index(similarity) == 0


# --- The fallback ladder (rec-spec §12.2) -----------------------------------


def test_no_evidence_produces_no_profile() -> None:
    profile = build_interest_profile([], FakeEmbeddings(), config=CONFIG)

    assert profile.strategy is ProfileStrategy.NONE
    assert profile.is_empty


def test_one_or_two_books_become_their_own_queries() -> None:
    profile = build_interest_profile(
        _evidence((1, 3.0), (11, 3.0)), FakeEmbeddings(), config=CONFIG
    )

    assert profile.strategy is ProfileStrategy.INDIVIDUAL_BOOKS
    assert len(profile.clusters) == 2
    assert all(cluster.member_count == 1 for cluster in profile.clusters)


def test_diverse_evidence_produces_multiple_interests() -> None:
    profile = build_interest_profile(
        _evidence((1, 3.0), (2, 3.0), (3, 3.0), (11, 3.0), (12, 3.0), (13, 3.0)),
        FakeEmbeddings(),
        config=CONFIG,
    )

    assert profile.strategy is ProfileStrategy.CLUSTERED
    assert len(profile.clusters) == 2
    groups = {frozenset(cluster.member_book_ids) for cluster in profile.clusters}
    assert groups == {frozenset({1, 2, 3}), frozenset({11, 12, 13})}


def test_a_coherent_profile_stays_one_interest() -> None:
    profile = build_interest_profile(
        _evidence((1, 3.0), (2, 3.0), (3, 3.0)), FakeEmbeddings(), config=CONFIG
    )

    assert profile.strategy is ProfileStrategy.SINGLE_CLUSTER
    assert len(profile.clusters) == 1


def test_noise_falls_back_to_strongest_books_rather_than_inventing_clusters() -> None:
    """rec-spec §12.2: "if thresholding yields only noise/singletons, fall
    back to ... rather than fabricating cluster structure"."""
    orthogonal = FakeEmbeddings(
        {1: [1, 0, 0, 0], 2: [0, 1, 0, 0], 3: [0, 0, 1, 0], 4: [0, 0, 0, 1]}
    )

    profile = build_interest_profile(
        _evidence((1, 4.0), (2, 3.0), (3, 2.0), (4, 1.0)), orthogonal, config=CONFIG
    )

    assert profile.strategy is ProfileStrategy.FALLBACK_CENTROID
    assert all(cluster.member_count == 1 for cluster in profile.clusters)
    # Strongest evidence first.
    assert profile.clusters[0].member_book_ids == (1,)


def test_books_without_embeddings_are_reported_not_silently_dropped() -> None:
    profile = build_interest_profile(
        _evidence((1, 3.0), (2, 3.0), (3, 3.0), (999, 5.0)), FakeEmbeddings(), config=CONFIG
    )

    assert profile.unembedded_book_ids == (999,)
    assert 999 not in {b for cluster in profile.clusters for b in cluster.member_book_ids}


def test_evidence_is_capped_and_strongest_first() -> None:
    lookup = FakeEmbeddings({index: [1.0, index * 0.001, 0.0] for index in range(50)})
    evidence = _evidence(*[(index, float(index)) for index in range(50)])

    profile = build_interest_profile(
        evidence, lookup, config=InterestProfileConfig(max_evidence_items=10)
    )

    members = {b for cluster in profile.clusters for b in cluster.member_book_ids}
    assert len(members) == 10
    assert members == set(range(40, 50))  # the ten heaviest


def test_one_book_with_several_signals_counts_once() -> None:
    """rec-spec §7.1's "avoid uncontrolled double-counting" — a saved *and*
    highly-rated book must not dominate a cluster by appearing twice."""
    evidence = [
        EvidenceItem(book_id=1, weight=3.0, source="shelf_save"),
        EvidenceItem(book_id=1, weight=4.0, source="rating"),
        EvidenceItem(book_id=2, weight=3.0, source="rating"),
        EvidenceItem(book_id=3, weight=3.0, source="rating"),
    ]

    profile = build_interest_profile(evidence, FakeEmbeddings(), config=CONFIG)

    members = [b for cluster in profile.clusters for b in cluster.member_book_ids]
    assert members.count(1) == 1
    assert profile.evidence_count == 3


def test_zero_and_negative_weights_are_ignored() -> None:
    profile = build_interest_profile(
        _evidence((1, 0.0), (2, -1.0)), FakeEmbeddings(), config=CONFIG
    )

    assert profile.strategy is ProfileStrategy.NONE


def test_interests_are_capped_and_ordered_by_weight() -> None:
    lookup = FakeEmbeddings(
        {index: [float(axis == index // 2) for axis in range(10)] for index in range(10)}
    )
    evidence = _evidence(*[(index, float(10 - index)) for index in range(10)])

    profile = build_interest_profile(
        evidence, lookup, config=InterestProfileConfig(max_interests=2, merge_threshold=0.5)
    )

    assert len(profile.clusters) <= 2
    weights = [cluster.weight for cluster in profile.clusters]
    assert weights == sorted(weights, reverse=True)


def test_query_strategy_is_configurable() -> None:
    """rec-spec §12.2 requires centroid-vs-medoid to stay configurable."""
    lookup = FakeEmbeddings()
    profile = build_interest_profile(_evidence((1, 3.0), (2, 3.0), (3, 3.0)), lookup, config=CONFIG)
    cluster = profile.clusters[0]

    centroid = query_vector_for(cluster, lookup, config=CONFIG)
    medoid = query_vector_for(
        cluster, lookup, config=InterestProfileConfig(query_strategy="medoid")
    )

    assert not np.allclose(centroid, medoid)
    representative, _ = lookup.vectors_for([cluster.representative_book_id])
    assert np.allclose(medoid, representative[0], atol=1e-6)


def test_profiles_are_deterministic() -> None:
    evidence = _evidence((1, 3.0), (2, 3.0), (3, 3.0), (11, 3.0), (12, 3.0))

    first = build_interest_profile(evidence, FakeEmbeddings(), config=CONFIG)
    second = build_interest_profile(evidence, FakeEmbeddings(), config=CONFIG)

    assert [c.member_book_ids for c in first.clusters] == [
        c.member_book_ids for c in second.clusters
    ]
    assert [c.interest_id for c in first.clusters] == [c.interest_id for c in second.clusters]


# --- Shelf profiles (rec-spec §12.1) ----------------------------------------


def test_shelf_profiles_are_one_vector_per_shelf() -> None:
    shelves = {
        "shelf-a": _evidence((1, 3.0), (2, 3.0)),
        "shelf-b": _evidence((11, 3.0), (12, 3.0)),
    }

    profiles = build_shelf_profiles(shelves, FakeEmbeddings())

    assert [profile.shelf_id for profile in profiles] == ["shelf-a", "shelf-b"]
    assert all(float(np.linalg.norm(p.query_vector)) == pytest.approx(1.0) for p in profiles)
    assert profiles[0].member_book_ids == (1, 2)


def test_a_shelf_is_not_clustered() -> None:
    """The reader already declared these books belong together; inferring
    otherwise would discard the most reliable signal in the system."""
    shelves = {"mixed": _evidence((1, 3.0), (11, 3.0))}

    profiles = build_shelf_profiles(shelves, FakeEmbeddings())

    assert len(profiles) == 1
    assert profiles[0].member_count == 2


def test_shelves_with_no_embedded_books_are_skipped() -> None:
    profiles = build_shelf_profiles({"empty": _evidence((999, 3.0))}, FakeEmbeddings())

    assert profiles == ()


# --- Summaries and labels (rec-spec §13) ------------------------------------


DESCRIPTORS = {
    1: BookDescriptor(1, "Dune", "Herbert", "science fiction", ("desert", "politics")),
    2: BookDescriptor(2, "Dune Messiah", "Herbert", "science fiction", ("desert", "empire")),
    3: BookDescriptor(3, "Children of Dune", "Herbert", "science fiction", ("desert",)),
}


def test_labels_are_built_from_shared_vocabulary() -> None:
    profile = build_interest_profile(
        _evidence((1, 3.0), (2, 3.0), (3, 3.0)), FakeEmbeddings(), config=CONFIG
    )

    summary = summarize_profile(profile, DESCRIPTORS)

    assert summary.interests[0].label.startswith("desert")
    assert "desert" in summary.interests[0].top_terms


def test_label_falls_back_to_the_representative_book() -> None:
    """rec-spec §13's own example form, for when members share no tags."""
    assert build_label((), (), "The Left Hand of Darkness") == (
        'Interest around "The Left Hand of Darkness"'
    )
    assert build_label((), ("fantasy",), "X") == "fantasy"
    assert build_label((), (), "") == "Unlabelled interest"


def test_a_term_used_by_one_book_of_several_does_not_label_the_interest() -> None:
    descriptors = {
        1: BookDescriptor(1, "A", tags=("shared", "unique-to-a")),
        2: BookDescriptor(2, "B", tags=("shared", "unique-to-b")),
        3: BookDescriptor(3, "C", tags=("shared",)),
    }
    profile = build_interest_profile(
        _evidence((1, 3.0), (2, 3.0), (3, 3.0)), FakeEmbeddings(), config=CONFIG
    )

    summary = summarize_profile(profile, descriptors)

    assert summary.interests[0].top_terms == ("shared",)


def test_summaries_never_contain_raw_vectors() -> None:
    """rec-spec §13: "Do not expose or print raw high-dimensional vectors by
    default." """
    profile = build_interest_profile(
        _evidence((1, 3.0), (2, 3.0), (3, 3.0)), FakeEmbeddings(), config=CONFIG
    )

    payload = summarize_profile(profile, DESCRIPTORS).as_dict()

    assert "query_vector" not in repr(payload)
    assert "vector" not in repr(payload).lower()


def test_summary_explains_why_the_books_were_grouped() -> None:
    profile = build_interest_profile(
        _evidence((1, 3.0), (2, 3.0), (3, 3.0)), FakeEmbeddings(), config=CONFIG
    )

    interest = summarize_profile(profile, DESCRIPTORS).interests[0]

    assert "3 book(s)" in interest.evidence_summary
    assert "rating" in interest.evidence_summary
    assert interest.representative_title in {"Dune", "Dune Messiah", "Children of Dune"}


def test_sparse_strategies_are_explained_in_notes() -> None:
    profile = build_interest_profile(_evidence((1, 3.0)), FakeEmbeddings(), config=CONFIG)

    summary = summarize_profile(profile, DESCRIPTORS)

    assert summary.strategy == "individual_books"
    assert any("too few books" in note for note in summary.notes)


def test_summary_reports_unembedded_books() -> None:
    profile = build_interest_profile(
        _evidence((1, 3.0), (2, 3.0), (3, 3.0), (999, 1.0)), FakeEmbeddings(), config=CONFIG
    )

    summary = summarize_profile(profile, DESCRIPTORS)

    assert summary.unembedded_book_ids == (999,)
    assert any("no embedding" in note for note in summary.notes)


def test_summary_is_json_serializable() -> None:
    import json

    profile = build_interest_profile(
        _evidence((1, 3.0), (2, 3.0), (3, 3.0)), FakeEmbeddings(), config=CONFIG
    )

    payload = json.dumps(summarize_profile(profile, DESCRIPTORS).as_dict())

    assert json.loads(payload)["interests"][0]["interest_id"] == "i0"
