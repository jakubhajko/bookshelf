"""The five candidate generators (rec-spec §9, §10, §11, §14, §15).

Every generator is checked for the properties Phase R6 requires of all of
them — deterministic, honours exclusions, degrades rather than raises,
reports provenance, runs only on its intended surfaces, no internal
duplicates — and then for the behaviour that is specific to it.

Artifacts come from ``generator_world``: twelve books in three disjoint
taste groups, so "the fantasy reader got fantasy books" is checkable rather
than plausible.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from book_recommender.artifacts import LocalArtifactStorage
from book_recommender.config import GeneratorConfig
from book_recommender.contracts.context import (
    HomeContext,
    ShelfContext,
    SimilarBooksContext,
)
from book_recommender.generators import (
    AlsCandidateGenerator,
    CandidateGenerator,
    GeneratorId,
    GeneratorRequest,
    GeneratorStatus,
    ItemItemCFCandidateGenerator,
    PopularityCandidateGenerator,
    SemanticCandidateGenerator,
    SourceSimilarityCandidateGenerator,
)
from generator_world import (
    ALL_BOOKS,
    CATALOG,
    FANTASY,
    ROMANCE,
    SCIFI,
    SHELF_FANTASY,
    SHELF_SCIFI,
    build_all,
    interest_profile,
    load_als,
    load_content,
    load_item_cf,
    load_popularity,
    load_source_graph,
    user_context,
)


@pytest.fixture
def storage(tmp_path: Path) -> LocalArtifactStorage:
    return build_all(tmp_path)


@pytest.fixture
def generators(storage: LocalArtifactStorage) -> dict[GeneratorId, CandidateGenerator]:
    return {
        GeneratorId.ALS: AlsCandidateGenerator(load_als(storage)),
        GeneratorId.ITEM_CF: ItemItemCFCandidateGenerator(load_item_cf(storage)),
        GeneratorId.SEMANTIC: SemanticCandidateGenerator(load_content(storage)),
        GeneratorId.SOURCE_SIMILARITY: SourceSimilarityCandidateGenerator(
            load_source_graph(storage)
        ),
        GeneratorId.POPULARITY: PopularityCandidateGenerator(
            load_popularity(storage).ranking, model_version="fixture"
        ),
    }


def fantasy_reader_request(**overrides: object) -> GeneratorRequest:
    """A reader whose entire evidence is the fantasy group."""
    defaults: dict[str, object] = {
        "user_context": user_context(
            ratings=[(101, 10), (102, 9)],
            saved=[(103, SHELF_FANTASY)],
        ),
        "surface_context": HomeContext(),
        "count": 6,
        "semantic_profile": interest_profile(
            clusters=[("c0", 0, (101, 102, 103), 9.0)],
            shelves=[(SHELF_FANTASY, 0, (103,), 3.0)],
        ),
    }
    defaults.update(overrides)
    return GeneratorRequest(**defaults)  # type: ignore[arg-type]


# --- Properties every generator must have ---------------------------------


ALL_IDS = [
    GeneratorId.ALS,
    GeneratorId.ITEM_CF,
    GeneratorId.SEMANTIC,
    GeneratorId.SOURCE_SIMILARITY,
    GeneratorId.POPULARITY,
]


@pytest.mark.parametrize("generator_id", ALL_IDS)
class TestEveryGenerator:
    def test_is_deterministic(
        self, generators: dict[GeneratorId, CandidateGenerator], generator_id: GeneratorId
    ) -> None:
        """The engine's order is authoritative and gets persisted
        (ADR-0006/0007); a non-deterministic generator makes the batch
        unreproducible and every offline evaluation unstable."""
        generator = generators[generator_id]
        request = fantasy_reader_request()
        first = generator.generate(request)
        second = generator.generate(request)
        assert first.candidates == second.candidates

    def test_reports_its_own_id_and_provenance(
        self, generators: dict[GeneratorId, CandidateGenerator], generator_id: GeneratorId
    ) -> None:
        result = generators[generator_id].generate(fantasy_reader_request())
        assert result.generator is generator_id
        assert all(candidate.generator is generator_id for candidate in result.candidates)
        assert all(candidate.provenance for candidate in result.candidates)

    def test_never_returns_a_book_twice(
        self, generators: dict[GeneratorId, CandidateGenerator], generator_id: GeneratorId
    ) -> None:
        result = generators[generator_id].generate(fantasy_reader_request())
        assert len(result.book_ids) == len(set(result.book_ids))

    def test_ranks_are_one_based_and_contiguous(
        self, generators: dict[GeneratorId, CandidateGenerator], generator_id: GeneratorId
    ) -> None:
        result = generators[generator_id].generate(fantasy_reader_request())
        assert [c.rank for c in result.candidates] == list(range(1, len(result.candidates) + 1))

    def test_honours_the_exclusion_set(
        self, generators: dict[GeneratorId, CandidateGenerator], generator_id: GeneratorId
    ) -> None:
        """Application-owned eligibility stays outside the engine, but every
        generator must apply what the application resolved (CLAUDE.md)."""
        excluded = frozenset({104, 105, 106})
        result = generators[generator_id].generate(
            fantasy_reader_request(excluded_book_ids=excluded, count=12)
        )
        assert not (set(result.book_ids) & excluded)

    def test_respects_the_requested_count(
        self, generators: dict[GeneratorId, CandidateGenerator], generator_id: GeneratorId
    ) -> None:
        result = generators[generator_id].generate(fantasy_reader_request(count=2))
        assert len(result.candidates) <= 2

    def test_a_cold_reader_degrades_rather_than_raises(
        self, generators: dict[GeneratorId, CandidateGenerator], generator_id: GeneratorId
    ) -> None:
        """rec-spec §27: a reader with no evidence is a cold-start path, not
        an error. Popularity is the one that must still produce candidates —
        it is the fallback the others degrade onto."""
        result = generators[generator_id].generate(
            GeneratorRequest(
                user_context=user_context(),
                surface_context=HomeContext(),
                count=5,
                semantic_profile=None,
            )
        )
        if generator_id is GeneratorId.POPULARITY:
            assert result.status is GeneratorStatus.OK
            assert result.candidates
        else:
            assert result.status is GeneratorStatus.NO_EVIDENCE
            assert not result.candidates


@pytest.mark.parametrize(
    ("generator_id", "construct"),
    [
        (GeneratorId.ALS, lambda: AlsCandidateGenerator(None)),
        (GeneratorId.ITEM_CF, lambda: ItemItemCFCandidateGenerator(None)),
        (GeneratorId.SEMANTIC, lambda: SemanticCandidateGenerator(None)),
        (GeneratorId.SOURCE_SIMILARITY, lambda: SourceSimilarityCandidateGenerator(None)),
        (GeneratorId.POPULARITY, lambda: PopularityCandidateGenerator(None)),
    ],
)
def test_a_missing_artifact_is_reported_not_hidden(
    generator_id: GeneratorId, construct: object
) -> None:
    """rec-spec §16: "Do not hide missing required artifacts." An absent
    artifact and an unlucky query both produce zero candidates, and only one
    of them means something is broken."""
    generator: CandidateGenerator = construct()  # type: ignore[operator]
    result = generator.generate(fantasy_reader_request())
    assert result.status is GeneratorStatus.NO_ARTIFACT
    assert not result.candidates
    assert result.diagnostics["reason"]


# --- Popularity (rec-spec §15) --------------------------------------------


class TestPopularityGenerator:
    def test_serves_the_artifact_order_unchanged(self, storage: LocalArtifactStorage) -> None:
        """The builder owns the Bayesian-shrunk score; this generator has no
        database to recompute it from and must not reorder it."""
        ranking = load_popularity(storage).ranking
        result = PopularityCandidateGenerator(ranking).generate(fantasy_reader_request(count=5))
        assert result.book_ids == tuple(book_id for book_id, _ in ranking[:5])

    def test_works_for_a_reader_with_no_evidence_at_all(
        self, storage: LocalArtifactStorage
    ) -> None:
        """rec-spec §15: the universal fallback and cold-start source."""
        result = PopularityCandidateGenerator(load_popularity(storage).ranking).generate(
            GeneratorRequest(user_context=user_context(), surface_context=HomeContext(), count=3)
        )
        assert len(result.candidates) == 3
        assert result.status is GeneratorStatus.OK


# --- ALS (rec-spec §9) -----------------------------------------------------


class TestAlsGenerator:
    def test_a_fantasy_reader_gets_the_rest_of_the_fantasy_group(
        self, storage: LocalArtifactStorage
    ) -> None:
        result = AlsCandidateGenerator(load_als(storage)).generate(fantasy_reader_request())
        assert result.book_ids[0] == 104
        assert 104 in result.book_ids

    def test_the_readers_own_seed_books_are_never_recommended_back(
        self, storage: LocalArtifactStorage
    ) -> None:
        """A reader's own books scoring highly against their own folded-in
        factor is arithmetic, not a recommendation."""
        result = AlsCandidateGenerator(load_als(storage)).generate(fantasy_reader_request(count=12))
        assert not ({101, 102, 103} & set(result.book_ids))

    def test_does_not_run_on_similar_books(self, storage: LocalArtifactStorage) -> None:
        """rec-spec §20.3: global personalization is absent from Similar
        Books — that is what turns "what is like this book" into "more books
        you may like"."""
        result = AlsCandidateGenerator(load_als(storage)).generate(
            fantasy_reader_request(surface_context=SimilarBooksContext(source_book_id=101))
        )
        assert result.status is GeneratorStatus.NOT_APPLICABLE
        assert not result.candidates

    def test_shelf_folds_in_the_shelf_as_a_pseudo_user(self, storage: LocalArtifactStorage) -> None:
        """rec-spec §20.2. The reader's global taste is romance; the target
        shelf is science fiction. The shelf must win, or shelf discovery is
        just Home with extra steps."""
        generator = AlsCandidateGenerator(load_als(storage))
        romance_reader = user_context(ratings=[(109, 10), (110, 10)])
        result = generator.generate(
            GeneratorRequest(
                user_context=romance_reader,
                surface_context=ShelfContext(
                    shelf_id=SHELF_SCIFI,
                    shelf_name="Sci-fi",
                    shelf_description=None,
                    shelf_book_ids=frozenset({105, 106}),
                ),
                count=4,
            )
        )
        # Only two sci-fi books remain once the shelf's own are excluded, so
        # a request for four legitimately reaches past the group. What matters
        # is that the shelf, not the reader's romance taste, leads.
        assert set(result.book_ids[:2]) == {107, 108}

    def test_fold_in_changes_with_the_profile_but_never_mutates_item_factors(
        self, storage: LocalArtifactStorage
    ) -> None:
        """rec-spec §9.2: the global model is not retrained when one reader
        saves a book."""
        artifact = load_als(storage)
        before = artifact.item_factors.copy()
        generator = AlsCandidateGenerator(artifact)

        fantasy = generator.generate(fantasy_reader_request(count=4))
        romance = generator.generate(
            fantasy_reader_request(
                user_context=user_context(ratings=[(109, 10), (110, 9)]), count=4
            )
        )

        assert fantasy.book_ids != romance.book_ids
        assert set(romance.book_ids[:2]) <= set(ROMANCE)
        assert set(fantasy.book_ids[:1]) <= set(FANTASY)
        assert np.array_equal(artifact.item_factors, before)

    def test_evidence_absent_from_the_trained_model_is_reported(
        self, storage: LocalArtifactStorage
    ) -> None:
        """Scoring against a zero vector would rank by nothing at all and
        look like a working recommendation."""
        result = AlsCandidateGenerator(load_als(storage)).generate(
            fantasy_reader_request(user_context=user_context(ratings=[(9999, 10)]))
        )
        assert result.status is GeneratorStatus.NO_EVIDENCE
        assert not result.candidates


# --- Item-item CF (rec-spec §10) ------------------------------------------


class TestItemCfGenerator:
    def test_retrieves_neighbours_of_the_seeds(self, storage: LocalArtifactStorage) -> None:
        result = ItemItemCFCandidateGenerator(load_item_cf(storage)).generate(
            fantasy_reader_request()
        )
        assert result.book_ids == (104,)

    def test_seed_weight_decides_the_order(self, storage: LocalArtifactStorage) -> None:
        """rec-spec §10: "weight seeds according to signal policy". A 10/10
        rating must pull harder than a 7/10 one."""
        generator = ItemItemCFCandidateGenerator(load_item_cf(storage))
        result = generator.generate(
            fantasy_reader_request(
                user_context=user_context(ratings=[(101, 7), (109, 10)]),
                semantic_profile=None,
                count=6,
            )
        )
        # 109's romance neighbours outrank 101's fantasy neighbours.
        assert set(result.book_ids[:3]) <= set(ROMANCE)

    def test_similar_books_seeds_from_the_source_book_only(
        self, storage: LocalArtifactStorage
    ) -> None:
        """rec-spec §20.3."""
        result = ItemItemCFCandidateGenerator(load_item_cf(storage)).generate(
            fantasy_reader_request(surface_context=SimilarBooksContext(source_book_id=105), count=6)
        )
        assert set(result.book_ids) <= set(SCIFI) - {105}

    def test_seeds_are_not_returned_as_their_own_recommendations(
        self, storage: LocalArtifactStorage
    ) -> None:
        result = ItemItemCFCandidateGenerator(load_item_cf(storage)).generate(
            fantasy_reader_request(count=12)
        )
        assert not ({101, 102, 103} & set(result.book_ids))


# --- Source similarity (rec-spec §14) -------------------------------------


class TestSourceSimilarityGenerator:
    def test_aggregates_edges_of_the_seed_books(self, storage: LocalArtifactStorage) -> None:
        result = SourceSimilarityCandidateGenerator(load_source_graph(storage)).generate(
            fantasy_reader_request()
        )
        assert result.book_ids == (104,)
        assert result.diagnostics["seeds_with_edges"] == 3

    def test_similar_books_uses_the_source_books_edges(self, storage: LocalArtifactStorage) -> None:
        """rec-spec §20.3 makes this the strongest generator on Similar."""
        result = SourceSimilarityCandidateGenerator(load_source_graph(storage)).generate(
            fantasy_reader_request(surface_context=SimilarBooksContext(source_book_id=109), count=6)
        )
        assert set(result.book_ids) <= set(ROMANCE) - {109}

    def test_a_book_with_no_edges_degrades_quietly(self, storage: LocalArtifactStorage) -> None:
        """rec-spec §27: "source graph empty for a book: Similar uses
        item-CF + semantic"."""
        result = SourceSimilarityCandidateGenerator(load_source_graph(storage)).generate(
            fantasy_reader_request(
                surface_context=SimilarBooksContext(source_book_id=9999), count=6
            )
        )
        assert result.status is GeneratorStatus.EMPTY
        assert not result.candidates

    def test_reports_its_edge_provenance(self, storage: LocalArtifactStorage) -> None:
        """rec-spec §14: provenance must remain interpretable — this
        generator represents source edges and nothing else."""
        result = SourceSimilarityCandidateGenerator(load_source_graph(storage)).generate(
            fantasy_reader_request()
        )
        assert result.diagnostics["sources"] == ("goodreads",)

    def test_agreement_between_seeds_breaks_a_score_tie(
        self, storage: LocalArtifactStorage
    ) -> None:
        """On the live graph, dozens of candidates tie at exactly one seed
        weight (a single rank-0 edge). RRF reads only rank, so the tiebreak
        *is* the signal — and ordering by book_id alone would make it
        catalog-insertion order.

        Seeds 101, 105 and 106 all carry the shelf-save weight of 3.0:

        - 102 is 101's rank-0 edge      -> 3.0 / 1        = 3.0, one seed
        - 107 is 105's *and* 106's
          rank-1 edge                   -> 3.0/2 + 3.0/2  = 3.0, two seeds

        Both total exactly 3.0. 107 must lead, even though 102 has the lower
        id and would win a book_id-only tiebreak.
        """
        graph = load_source_graph(storage)
        result = SourceSimilarityCandidateGenerator(graph).generate(
            fantasy_reader_request(
                user_context=user_context(
                    saved=[
                        (101, SHELF_FANTASY),
                        (105, SHELF_SCIFI),
                        (106, SHELF_SCIFI),
                    ]
                ),
                count=6,
            )
        )
        scores = {c.book_id: c.score for c in result.candidates}
        assert scores[102] == scores[107] == 3.0
        assert result.book_ids[:2] == (107, 102)
        agreed = next(c for c in result.candidates if c.book_id == 107)
        assert dict(agreed.diagnostics) == {"seeds": 2}


# --- Semantic (rec-spec §11, §12, §20) ------------------------------------


class TestSemanticGenerator:
    def test_interests_and_shelves_produce_separate_query_provenance(
        self, storage: LocalArtifactStorage
    ) -> None:
        """rec-spec §28's generator criterion: "explicit shelf profiles and
        inferred interest profiles produce separate query provenance"."""
        result = SemanticCandidateGenerator(load_content(storage)).generate(
            fantasy_reader_request(
                semantic_profile=interest_profile(
                    clusters=[("c0", 0, (101,), 9.0)],
                    shelves=[(SHELF_SCIFI, 1, (105,), 8.0)],
                ),
                count=8,
            )
        )
        provenances = {candidate.provenance for candidate in result.candidates}
        assert any(p.startswith("interest:") for p in provenances)
        assert any(p.startswith("shelf:") for p in provenances)
        assert result.diagnostics["queries"] == 2

    def test_multiple_interests_are_all_represented(self, storage: LocalArtifactStorage) -> None:
        """The point of rec-spec §12.2. A single dense interest must not take
        every slot."""
        result = SemanticCandidateGenerator(load_content(storage)).generate(
            fantasy_reader_request(
                semantic_profile=interest_profile(
                    clusters=[("c0", 0, (101,), 9.0), ("c1", 2, (109,), 4.0)],
                ),
                count=4,
            )
        )
        found = set(result.book_ids)
        assert found & set(FANTASY)
        assert found & set(ROMANCE)

    def test_the_strongest_interest_leads(self, storage: LocalArtifactStorage) -> None:
        result = SemanticCandidateGenerator(load_content(storage)).generate(
            fantasy_reader_request(
                semantic_profile=interest_profile(
                    clusters=[("c0", 2, (109,), 1.0), ("c1", 0, (101,), 9.0)],
                ),
                count=4,
            )
        )
        assert result.candidates[0].book_id in FANTASY

    def test_shelf_surface_queries_the_target_shelf_only(
        self, storage: LocalArtifactStorage
    ) -> None:
        """rec-spec §20.2: the goal is to extend *this shelf*. The reader's
        global fantasy interest must not bleed into a sci-fi shelf."""
        result = SemanticCandidateGenerator(load_content(storage)).generate(
            GeneratorRequest(
                user_context=user_context(saved=[(105, SHELF_SCIFI)]),
                surface_context=ShelfContext(
                    shelf_id=SHELF_SCIFI,
                    shelf_name="Sci-fi",
                    shelf_description=None,
                    shelf_book_ids=frozenset({105}),
                ),
                count=6,
                semantic_profile=interest_profile(
                    clusters=[("c0", 0, (101,), 9.0)],
                    shelves=[(SHELF_SCIFI, 1, (105,), 3.0)],
                ),
            )
        )
        assert result.candidates
        assert set(result.book_ids) <= set(SCIFI)
        assert {c.provenance for c in result.candidates} == {"target_shelf"}

    def test_similar_books_queries_the_source_book_vector(
        self, storage: LocalArtifactStorage
    ) -> None:
        result = SemanticCandidateGenerator(load_content(storage)).generate(
            fantasy_reader_request(surface_context=SimilarBooksContext(source_book_id=109), count=4)
        )
        assert set(result.book_ids) <= set(ROMANCE)
        assert {c.provenance for c in result.candidates} == {"source_book"}

    def test_a_source_book_with_no_embedding_degrades(self, storage: LocalArtifactStorage) -> None:
        """Risk #108: books added since the last content build have no
        vector. rec-spec §27 makes that a degradation, not an error."""
        result = SemanticCandidateGenerator(load_content(storage)).generate(
            fantasy_reader_request(
                surface_context=SimilarBooksContext(source_book_id=9999), count=4
            )
        )
        assert result.status is GeneratorStatus.NO_EVIDENCE
        assert not result.candidates

    def test_excludes_ineligible_items_before_selection(
        self, storage: LocalArtifactStorage
    ) -> None:
        """rec-spec §28: "semantic exact retrieval excludes ineligible
        items". Applied before top-K, so a heavily-excluded reader still gets
        a full page rather than a short one."""
        excluded = frozenset({102, 103, 104})
        result = SemanticCandidateGenerator(load_content(storage)).generate(
            fantasy_reader_request(
                excluded_book_ids=excluded,
                semantic_profile=interest_profile(clusters=[("c0", 0, (101,), 9.0)]),
                count=3,
            )
        )
        assert not (set(result.book_ids) & excluded)

    def test_unrelated_results_are_dropped_by_the_score_floor(
        self, storage: LocalArtifactStorage
    ) -> None:
        """A thin profile would otherwise pad the feed with books that
        merely happen to be least-unrelated to the query."""
        generator = SemanticCandidateGenerator(
            load_content(storage), config=GeneratorConfig(semantic_min_score=0.9)
        )
        result = generator.generate(
            fantasy_reader_request(
                semantic_profile=interest_profile(clusters=[("c0", 0, (101,), 9.0)]),
                count=12,
            )
        )
        assert set(result.book_ids) <= set(FANTASY)

    def test_a_profile_with_no_interests_reports_no_evidence(
        self, storage: LocalArtifactStorage
    ) -> None:
        result = SemanticCandidateGenerator(load_content(storage)).generate(
            fantasy_reader_request(semantic_profile=interest_profile())
        )
        assert result.status is GeneratorStatus.NO_EVIDENCE

    def test_query_count_is_capped(self, storage: LocalArtifactStorage) -> None:
        generator = SemanticCandidateGenerator(
            load_content(storage), config=GeneratorConfig(max_semantic_queries=1)
        )
        result = generator.generate(
            fantasy_reader_request(
                semantic_profile=interest_profile(
                    clusters=[("c0", 0, (101,), 9.0), ("c1", 2, (109,), 4.0)],
                ),
                count=6,
            )
        )
        assert result.diagnostics["queries"] == 1

    def test_diagnostics_carry_no_vectors(self, storage: LocalArtifactStorage) -> None:
        """rec-spec §13 and CLAUDE.md: diagnostics must not become a
        sensitive-data dump, and raw high-dimensional vectors never leave."""
        result = SemanticCandidateGenerator(load_content(storage)).generate(
            fantasy_reader_request()
        )
        payload = repr(result.diagnostics) + repr(
            [candidate.diagnostics for candidate in result.candidates]
        )
        assert "array" not in payload
        assert "ndarray" not in payload


def test_every_generator_satisfies_the_protocol(
    generators: dict[GeneratorId, CandidateGenerator],
) -> None:
    """Structural conformance, checked rather than assumed — nothing
    inherits from the protocol, so nothing enforces it at class definition."""
    for generator_id, generator in generators.items():
        # `CandidateGenerator` is not `@runtime_checkable` on purpose — an
        # isinstance check against it would only verify the two names exist,
        # which is weaker than what mypy already proves structurally. This
        # checks the part a type checker cannot: that each generator reports
        # the identity it was registered under.
        assert callable(generator.generate)
        assert generator.generator_id is generator_id


def test_catalog_and_fixture_agree() -> None:
    assert len(CATALOG) == len(ALL_BOOKS)
