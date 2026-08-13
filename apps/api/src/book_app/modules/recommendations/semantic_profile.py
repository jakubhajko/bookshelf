"""Assembling a reader's semantic profile from application state
(rec-spec §12, §13).

The bridge between the application (which knows what a reader did) and
``book_recommender.profiling`` (which knows how to turn that into
interests). Everything inferential lives in the recommender package; this
module only gathers evidence and applies the signal policy.

That split is what makes rec-spec §13's requirement enforceable — "The
inspection path must reuse the **same profiling code** used by the live
recommender" — because there is only one place the clustering could live,
and it is not here.
"""

from __future__ import annotations

from dataclasses import dataclass

from book_recommender.artifacts import ItemMetadataTable
from book_recommender.config import (
    INTEREST_PROFILE_DEFAULT,
    SIGNAL_WEIGHTS_DEFAULT,
    InterestProfileConfig,
    SignalWeights,
)
from book_recommender.contracts.context import UserContext
from book_recommender.profiling import (
    BookDescriptor,
    EmbeddingLookup,
    EvidenceItem,
    InterestProfile,
    ProfileSummary,
    ShelfProfile,
    build_interest_profile,
    build_shelf_profiles,
    summarize_profile,
)


@dataclass(frozen=True)
class SemanticProfile:
    """Inferred interests plus explicit shelf profiles for one reader."""

    interests: InterestProfile
    shelves: tuple[ShelfProfile, ...]

    @property
    def is_empty(self) -> bool:
        return self.interests.is_empty and not self.shelves

    def combined(self) -> InterestProfile:
        """Interests and shelf profiles in one :class:`InterestProfile`.

        The two are built separately — clustering does not know about
        shelves — but every consumer wants them together: the inspection
        summary, and the semantic candidate generator, which issues one
        query per interest *and* per shelf (rec-spec §20.1). Kept here so
        there is one definition of "the reader's full semantic profile"
        rather than each caller re-assembling it slightly differently.
        """
        return InterestProfile(
            strategy=self.interests.strategy,
            clusters=self.interests.clusters,
            shelves=self.shelves,
            unembedded_book_ids=self.interests.unembedded_book_ids,
            evidence_count=self.interests.evidence_count,
            config=self.interests.config,
        )


def collect_evidence(
    context: UserContext, *, weights: SignalWeights = SIGNAL_WEIGHTS_DEFAULT
) -> list[EvidenceItem]:
    """Turn a ``UserContext`` into weighted positive evidence (rec-spec §7.1).

    Only positive signals appear. Not-Interested is an exclusion the
    application already enforces, and low ratings are negative evidence that
    rec-spec §7.1 keeps out of the semantic *profile* — a book someone
    disliked should not pull their interest centroid toward it.
    """
    evidence: list[EvidenceItem] = [
        EvidenceItem(book_id=seed.book_id, weight=weights.taste_seed, source="taste_seed")
        for seed in context.taste_seeds
    ]
    evidence += [
        EvidenceItem(book_id=rating.book_id, weight=weight, source="rating")
        for rating in context.ratings
        if (weight := weights.for_rating(rating.rating_value)) > 0
    ]
    evidence += [
        EvidenceItem(book_id=saved.book_id, weight=weights.shelf_save, source="shelf_save")
        for saved in context.saved_books
    ]
    # Not-Interested books are excluded outright, even if some other signal
    # would otherwise have introduced them.
    rejected = set(context.not_interested_book_ids)
    return [item for item in evidence if item.book_id not in rejected]


def build_semantic_profile(
    context: UserContext,
    embeddings: EmbeddingLookup,
    *,
    weights: SignalWeights = SIGNAL_WEIGHTS_DEFAULT,
    config: InterestProfileConfig = INTEREST_PROFILE_DEFAULT,
) -> SemanticProfile:
    evidence = collect_evidence(context, weights=weights)
    interests = build_interest_profile(evidence, embeddings, config=config)

    shelf_members: dict[str, list[EvidenceItem]] = {}
    for saved in context.saved_books:
        if saved.book_id in set(context.not_interested_book_ids):
            continue
        shelf_members.setdefault(str(saved.shelf_id), []).append(
            EvidenceItem(book_id=saved.book_id, weight=weights.shelf_save, source="shelf_save")
        )

    return SemanticProfile(
        interests=interests,
        shelves=build_shelf_profiles(shelf_members, embeddings),
    )


def summarize(
    profile: SemanticProfile,
    metadata: ItemMetadataTable,
    *,
    shelf_names: dict[str, str] | None = None,
) -> ProfileSummary:
    """Human-inspectable summary, using the item-metadata artifact for
    titles/genres/tags rather than re-querying PostgreSQL."""
    book_ids = {
        book_id for cluster in profile.interests.clusters for book_id in cluster.member_book_ids
    }
    book_ids |= {book_id for shelf in profile.shelves for book_id in shelf.member_book_ids}
    book_ids |= {cluster.representative_book_id for cluster in profile.interests.clusters}
    book_ids |= {shelf.representative_book_id for shelf in profile.shelves}

    descriptors: dict[int, BookDescriptor] = {}
    for book_id in book_ids:
        row = metadata.get(book_id)
        if row is None:
            continue
        descriptors[book_id] = BookDescriptor(
            book_id=row.book_id,
            title=row.title,
            author=row.author,
            genre=row.genre,
            tags=row.tags,
        )

    return summarize_profile(profile.combined(), descriptors, shelf_names=shelf_names)
