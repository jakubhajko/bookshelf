"""Centralized, typed recommender configuration (rec-spec §26).

rec-spec §26 asks for typed configuration kept in categories rather than
"every tuning parameter as an environment variable": stable model/pipeline
defaults belong in code, deployment-specific *selection* belongs in
application settings. This module holds the first category — artifact and
model versions — because recommender Phase R3 is the first phase that
produces artifacts other than popularity.

The later categories (live signal weights, candidate quotas, per-surface RRF
weights, ranking feature weights, diversity parameters, interest-clustering
thresholds) are deliberately absent: they belong to the phases that
introduce the machinery they tune (R6-R7), and declaring empty placeholders
for them now would be inventing a contract before there is anything to
honour it.

``preprocessing_version`` is separate from an artifact's ``model_version``
on purpose. ``model_version`` is a build timestamp — it changes on every
rebuild. ``preprocessing_version`` changes only when the *meaning* of the
artifact's numbers changes, so it is the field that says "this artifact is
not comparable to the one before it" and the one to bump when editing a
builder's transform.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactFamily:
    """Where one artifact family lives and what produced it."""

    #: Matches the manifest's ``model_name`` and the ``model_versions`` row.
    name: str
    #: Path relative to the artifact storage root.
    directory: str
    preprocessing_version: str


POPULARITY = ArtifactFamily(
    name="popularity",
    directory="popularity/latest",
    # Bayesian-shrunk support × quality over ratings_count/bx_ratings/
    # bx_explicit/average_rating — see cli/build_popularity.py.
    preprocessing_version="popularity-bayesian-shrink-v1",
)

SOURCE_SIMILARITY = ArtifactFamily(
    name="source_similarity",
    directory="source_similarity/latest",
    # Goodreads similar-work edges as resolved by the catalog import, with
    # both endpoints required to be active books — see rec-spec §14.
    preprocessing_version="goodreads-resolved-edges-v1",
)

ALS = ArtifactFamily(
    name="als",
    directory="als/latest",
    # Implicit-feedback ALS over positive-only historical preference — see
    # HISTORICAL_TRANSFORM_V1 and cli/build_als.py.
    preprocessing_version="als-positive-only-v1",
)

ITEM_CF = ArtifactFamily(
    name="item_cf",
    directory="item_cf/latest",
    # Sparse item-item nearest neighbours over the same positive-only matrix.
    preprocessing_version="item-cf-topk-v1",
)

CONTENT = ArtifactFamily(
    name="content",
    directory="content/latest",
    # Normalized Qwen3 embeddings over the deterministic book text — see
    # book_recommender/content/ and cli/build_content_embeddings.py.
    preprocessing_version="content-qwen3-512-v1",
)

ITEM_METADATA = ArtifactFamily(
    name="item_metadata",
    directory="item_metadata/latest",
    # Title / primary author / top genre from the catalog. The cleaned
    # shelf-tag columns exist in the contract but are unpopulated until the
    # tag cleaner lands in R5.
    preprocessing_version="catalog-fields-v1",
)

#: Every artifact family the system builds.
FAMILIES: Mapping[str, ArtifactFamily] = {
    family.name: family
    for family in (POPULARITY, SOURCE_SIMILARITY, ITEM_METADATA, ALS, ITEM_CF, CONTENT)
}


# --- Training-data transform (rec-spec §7.2) --------------------------------


@dataclass(frozen=True)
class HistoricalInteractionTransform:
    """Historical Book-Crossing rating → positive-preference confidence.

    rec-spec §7.2 is unusually specific here, and every clause of it is a
    correctness rule rather than a tuning choice:

    - ``rating == 0`` is an **implicit positive** — the reader owned or
      shelved the book and left no score. Treating it as a zero or a
      negative would throw away 61% of the dataset (474,910 of 775,090 rows)
      and invert the meaning of the rest.
    - explicit ``1–5`` is negative evidence, and V1 **omits** it rather than
      feeding it to ALS as negative confidence. rec-spec §7.2: "Do not force
      negative-confidence ALS training in V1 merely because the library
      supports it." A positive-only baseline is the thing to beat first.
    - explicit ``6`` is ambiguous — roughly neutral. It is included or not
      by ``include_neutral``, and rec-spec §7.2 says to decide "based on
      evaluation", so the builder sweeps it rather than guessing.
    - there are **no timestamps**, so nothing here may weight by recency.

    ``confidence`` values feed implicit-feedback ALS, where the matrix value
    is the confidence that a positive preference is real, not a rating.
    """

    version: str
    #: Confidence for an implicit (rating 0) interaction.
    implicit_confidence: float
    #: Confidence per explicit rating. Ratings absent from this mapping are
    #: dropped from the positive matrix entirely.
    explicit_confidence: Mapping[int, float]
    #: Whether rating 6 (neutral) contributes at all.
    include_neutral: bool
    #: Global multiplier applied to every confidence.
    alpha: float = 1.0

    def confidence_for(self, rating: int) -> float | None:
        """``None`` means "not positive evidence — drop this row"."""
        if rating == 0:
            return self.alpha * self.implicit_confidence
        if rating == NEUTRAL_RATING and not self.include_neutral:
            return None
        weight = self.explicit_confidence.get(rating)
        return None if weight is None else self.alpha * weight

    def with_neutral(self, include: bool) -> HistoricalInteractionTransform:
        """The one variant the ALS builder sweeps, per rec-spec §7.2."""
        suffix = "with-neutral" if include else "no-neutral"
        base = self.version.rsplit("+", 1)[0]
        return HistoricalInteractionTransform(
            version=f"{base}+{suffix}",
            implicit_confidence=self.implicit_confidence,
            explicit_confidence=self.explicit_confidence,
            include_neutral=include,
            alpha=self.alpha,
        )


#: Explicit rating that means "approximately neutral" (rec-spec §7.1).
NEUTRAL_RATING = 6

#: Ratings that carry positive evidence at all. 1–5 are deliberately absent.
HISTORICAL_TRANSFORM_V1 = HistoricalInteractionTransform(
    version="bx-positive-only-v1+no-neutral",
    # Deliberately the weakest positive: an implicit row says "this reader
    # had some relationship with this book" and nothing more.
    implicit_confidence=1.0,
    explicit_confidence={
        NEUTRAL_RATING: 1.0,
        7: 2.0,
        8: 3.0,
        9: 4.0,
        10: 5.0,
    },
    include_neutral=False,
    alpha=1.0,
)


# --- Model training defaults (rec-spec §9, §10, §26) ------------------------


@dataclass(frozen=True)
class AlsConfig:
    """rec-spec §9.1: factors, regularization, iterations and the confidence
    transform all stay configurable, with defaults chosen by offline
    evaluation rather than asserted."""

    factors: int
    regularization: float
    iterations: int
    #: Fixed so a rebuild from identical input produces identical factors.
    random_state: int = 0

    @property
    def label(self) -> str:
        return f"f{self.factors}-r{self.regularization}-i{self.iterations}"


#: rec-spec §9.1 suggests "a practical factor count such as 64–128" and
#: selecting via offline evaluation. This is the starting point; the sweep in
#: cli/build_als.py is what picks the shipped one.
ALS_DEFAULT = AlsConfig(factors=96, regularization=0.05, iterations=20)

#: The grid the builder sweeps when asked to. Small on purpose — rec-spec
#: §9.1 says "a small reasonable config grid if compute permits", and the
#: point is to justify a default, not to search exhaustively.
ALS_SWEEP: tuple[AlsConfig, ...] = (
    AlsConfig(factors=64, regularization=0.05, iterations=20),
    AlsConfig(factors=96, regularization=0.05, iterations=20),
    AlsConfig(factors=128, regularization=0.05, iterations=20),
    AlsConfig(factors=96, regularization=0.01, iterations=20),
    AlsConfig(factors=96, regularization=0.10, iterations=20),
)

#: ALS fold-in regularization for live users (rec-spec §9.2). Separate from
#: training regularization because it solves a different problem: one user
#: against fixed item factors, often from very few positive items, where
#: under-regularizing produces a wild vector.
ALS_FOLD_IN_REGULARIZATION = 0.05


@dataclass(frozen=True)
class ItemCfConfig:
    """rec-spec §10: cosine baseline versus popularity-aware weighting,
    chosen on held-out data."""

    #: ``"cosine"`` or ``"bm25"``.
    similarity: str
    #: rec-spec §10: "configurable top-K neighbours per item (for example
    #: 100–200)".
    top_k: int
    #: BM25 only. ``k1`` controls confidence saturation, ``b`` how strongly
    #: popular items are discounted.
    bm25_k1: float = 1.2
    bm25_b: float = 0.75

    @property
    def label(self) -> str:
        return f"{self.similarity}-k{self.top_k}"


ITEM_CF_DEFAULT = ItemCfConfig(similarity="bm25", top_k=100)

ITEM_CF_SWEEP: tuple[ItemCfConfig, ...] = (
    ItemCfConfig(similarity="cosine", top_k=100),
    ItemCfConfig(similarity="bm25", top_k=100),
)


@dataclass(frozen=True)
class HoldoutConfig:
    """rec-spec §23.1: "Historical data has no timestamps, so use a
    documented per-user random/stratified holdout rather than pretending it
    is temporal." """

    #: Fraction of each eligible user's positive items held out.
    fraction: float = 0.2
    #: Users with fewer positives than this are kept whole in training and
    #: excluded from evaluation — holding one of three items out says more
    #: about the split than the model.
    min_interactions: int = 5
    #: Cap on held-out items per user, so the metrics are not dominated by a
    #: handful of readers with hundreds of books.
    max_held_out: int = 20
    random_state: int = 0


HOLDOUT_DEFAULT = HoldoutConfig()

#: Cutoffs reported by the evaluator (rec-spec §23.1).
EVALUATION_K_VALUES: tuple[int, ...] = (10, 20, 50)

#: Cutoff the sweeps *select* on, as opposed to merely report.
#:
#: The deepest cutoff, not the shallowest, and the reason is architectural.
#: These models are **candidate generators**, not the final ranker: ADR-0017
#: fuses several of them with weighted RRF and a deterministic ranker orders
#: what comes out. So a generator's job is to get relevant items into a deep
#: candidate pool in a sensible rank order — which is what NDCG@50 measures —
#: and its NDCG@10 measures a stage it is not responsible for.
#:
#: This is not metric-shopping after the fact; it changed one real decision.
#: On the live dataset, cosine item-CF beats BM25 by 3% at NDCG@10 while BM25
#: beats cosine by 21% on recall@50, 37% on catalog coverage, and has far less
#: popularity concentration (Gini 0.374 vs 0.577). Selecting at depth picks
#: BM25, which rec-spec §10's "offline metrics plus coverage/popularity
#: behavior" also points at. For ALS the two criteria agree on f128.
SELECTION_K = max(EVALUATION_K_VALUES)


# --- Content encoder (rec-spec §11.1, ADR-0018) -----------------------------


@dataclass(frozen=True)
class EncoderConfig:
    """rec-spec §11.1: "Use a swappable encoder abstraction ... Do not
    hard-code Qwen-specific behavior into serving contracts."

    Every field here is recorded in the content artifact's manifest, because
    changing any of them changes every vector and the artifact has to be able
    to say which encoder produced it.
    """

    name: str
    #: Output dimension. Qwen3 supports user-defined dimensions via Matryoshka
    #: truncation, so this is a real knob rather than a property of the model.
    dimension: int
    #: Token cap per book. Not a model limit — Qwen3-Embedding-0.6B accepts
    #: 32,768 — but a deliberate cost/quality choice: median book text is
    #: ~180 tokens and the 90th percentile ~380, so 512 covers the corpus
    #: while 32k would make the build ~40x slower for nothing.
    max_sequence_length: int = 512
    #: Measured on this catalog: batch 16 encodes 17.6 books/s on Apple MPS,
    #: against 15.0 at batch 32 and 11.0 at batch 64.
    batch_size: int = 16
    #: rec-spec §11.1 wants a pinned revision "when possible". None means the
    #: build records whatever the hub resolved, rather than claiming a pin it
    #: does not have.
    revision: str | None = None
    #: Instruction/prompt applied to documents. Empty for V1: Qwen3 is
    #: instruction-aware for *queries*, and the catalog side is plain
    #: documents. Versioned so adding one later is visible.
    prompt: str = ""
    prompt_version: str = "noprompt-v1"


#: rec-spec §11.1's stated default.
ENCODER_DEFAULT = EncoderConfig(name="Qwen/Qwen3-Embedding-0.6B", dimension=512)


# --- Semantic profiling (rec-spec §12.2, ADR-0016) --------------------------


@dataclass(frozen=True)
class InterestProfileConfig:
    """Threshold-based interest clustering. rec-spec §12.2: "distance/
    similarity threshold rather than fixed K" and "Do not force every user
    into the same number of interests."
    """

    #: Average-linkage cosine *similarity* above which two clusters merge.
    #: Higher means more, tighter interests. 0.55 is deliberately permissive:
    #: on normalized Qwen3 vectors, unrelated books sit around 0.2-0.35 and
    #: same-series books above 0.7, so this splits genuinely different
    #: interests while keeping a coherent taste together.
    merge_threshold: float = 0.55
    #: rec-spec §12.2: "Cap the clustering input to a configurable
    #: strongest/recent subset (for example around 100 items)".
    max_evidence_items: int = 100
    #: Below this, a cluster is treated as noise and folded into the
    #: individual-books fallback rather than presented as an interest.
    min_cluster_size: int = 2
    #: Guard for the 1-2 item case (rec-spec §12.2's fallback ladder).
    min_items_for_clustering: int = 3
    #: How many interests may be returned. Bounds both work and the size of
    #: the diagnostics a request can carry.
    max_interests: int = 8
    #: ``"centroid"`` or ``"medoid"`` — rec-spec §12.2 requires this stay
    #: configurable "for future offline comparison".
    query_strategy: str = "centroid"


INTEREST_PROFILE_DEFAULT = InterestProfileConfig()


@dataclass(frozen=True)
class SignalWeights:
    """Evidence strength per raw signal, for semantic profiling
    (rec-spec §7.1's "Semantic profile" column).

    These are the weights that turn *what a reader did* into *how much this
    book counts* when building an interest. rec-spec §7: "All numeric values
    below are configurable defaults, not universal truths."
    """

    taste_seed: float = 3.0
    rating_9_10: float = 4.0
    rating_8: float = 3.0
    rating_7: float = 1.5
    shelf_save: float = 3.0
    #: rec-spec §7.1 puts opens at "low positive if recent" for the semantic
    #: profile and explicitly not in long-term CF evidence.
    book_opened: float = 0.5

    def for_rating(self, internal_rating: int) -> float:
        """Internal 1-10 scale. 6 and below contribute nothing positive —
        rec-spec §7.1 calls 6 neutral and 1-5 negative."""
        if internal_rating >= 9:
            return self.rating_9_10
        if internal_rating == 8:
            return self.rating_8
        if internal_rating == 7:
            return self.rating_7
        return 0.0


SIGNAL_WEIGHTS_DEFAULT = SignalWeights()
