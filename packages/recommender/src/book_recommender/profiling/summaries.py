"""Human-inspectable interest summaries (rec-spec §13, ADR-0016).

rec-spec §13 makes inspectability a *feature*, not a debugging afterthought:
"Every inferred interest cluster must have a deterministic diagnostic
representation separate from its raw embedding vector."

Two rules shape everything here.

**Labels are deterministic and non-LLM.** rec-spec §13: "``label`` must be
deterministic and non-LLM-dependent in V1. Build labels from top cleaned
tags/genres plus the representative/medoid book when needed." So a label is
assembled by counting the cleaned tags and genres its member books share,
and falls back to the spec's own example form — ``Interest around "The Left
Hand of Darkness"`` — when the members share no vocabulary.

**Raw vectors never appear.** rec-spec §13: "Do not expose or print raw
high-dimensional vectors by default." A summary carries ids, words and
counts. This is also the rule that keeps recommendation diagnostics from
becoming the sensitive-data dump CLAUDE.md warns about.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from book_recommender.profiling.interests import (
    MAX_SUMMARY_MEMBERS,
    MAX_SUMMARY_TERMS,
    InterestCluster,
    InterestProfile,
    ShelfProfile,
)


@dataclass(frozen=True)
class BookDescriptor:
    """The metadata a summary needs about one book.

    Deliberately the exact shape the item-metadata artifact already
    provides, so inspection reads the same data the ranker does rather than
    re-querying PostgreSQL.
    """

    book_id: int
    title: str
    author: str = ""
    genre: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class InterestClusterSummary:
    """rec-spec §13's required structure."""

    interest_id: str
    label: str
    weight: float
    member_count: int
    representative_book_id: int
    representative_title: str
    member_book_ids: tuple[int, ...]
    top_terms: tuple[str, ...]
    top_genres: tuple[str, ...]
    evidence_summary: str
    coherence: float

    def as_dict(self) -> dict[str, object]:
        """JSON-ready, for the inspection command's ``--json`` mode."""
        return {
            "interest_id": self.interest_id,
            "label": self.label,
            "weight": round(self.weight, 4),
            "member_count": self.member_count,
            "representative_book_id": self.representative_book_id,
            "representative_title": self.representative_title,
            "member_book_ids": list(self.member_book_ids),
            "top_terms": list(self.top_terms),
            "top_genres": list(self.top_genres),
            "evidence_summary": self.evidence_summary,
            "coherence": round(self.coherence, 4),
        }


@dataclass(frozen=True)
class ShelfProfileSummary:
    shelf_id: str
    shelf_name: str
    label: str
    member_count: int
    representative_book_id: int
    representative_title: str
    top_terms: tuple[str, ...]
    top_genres: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "shelf_id": self.shelf_id,
            "shelf_name": self.shelf_name,
            "label": self.label,
            "member_count": self.member_count,
            "representative_book_id": self.representative_book_id,
            "representative_title": self.representative_title,
            "top_terms": list(self.top_terms),
            "top_genres": list(self.top_genres),
        }


@dataclass(frozen=True)
class ProfileSummary:
    """The whole inspectable profile (rec-spec §13's CLI output)."""

    strategy: str
    evidence_count: int
    interests: tuple[InterestClusterSummary, ...] = ()
    shelves: tuple[ShelfProfileSummary, ...] = ()
    unembedded_book_ids: tuple[int, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        return {
            "strategy": self.strategy,
            "evidence_count": self.evidence_count,
            "interests": [interest.as_dict() for interest in self.interests],
            "shelves": [shelf.as_dict() for shelf in self.shelves],
            "unembedded_book_ids": list(self.unembedded_book_ids),
            "notes": list(self.notes),
        }


def summarize_profile(
    profile: InterestProfile,
    descriptors: Mapping[int, BookDescriptor],
    *,
    shelf_names: Mapping[str, str] | None = None,
) -> ProfileSummary:
    notes: list[str] = []
    if profile.unembedded_book_ids:
        notes.append(
            f"{len(profile.unembedded_book_ids)} book(s) had no embedding — "
            "added since the last content build"
        )
    if profile.strategy.value == "individual_books":
        notes.append("too few books to cluster; each book is its own query")
    if profile.strategy.value == "fallback_centroid":
        notes.append("clustering found no coherent group; using strongest individual books")

    return ProfileSummary(
        strategy=profile.strategy.value,
        evidence_count=profile.evidence_count,
        interests=tuple(summarize_cluster(cluster, descriptors) for cluster in profile.clusters),
        shelves=tuple(
            summarize_shelf(shelf, descriptors, (shelf_names or {}).get(shelf.shelf_id, ""))
            for shelf in profile.shelves
        ),
        unembedded_book_ids=profile.unembedded_book_ids,
        notes=tuple(notes),
    )


def summarize_cluster(
    cluster: InterestCluster, descriptors: Mapping[int, BookDescriptor]
) -> InterestClusterSummary:
    members = [
        descriptors[book_id] for book_id in cluster.member_book_ids if book_id in descriptors
    ]
    representative = descriptors.get(cluster.representative_book_id)
    representative_title = representative.title if representative else ""

    top_terms = _top_values(member.tags for member in members)
    top_genres = _top_values(((member.genre,) if member.genre else ()) for member in members)

    return InterestClusterSummary(
        interest_id=cluster.interest_id,
        label=build_label(top_terms, top_genres, representative_title),
        weight=cluster.weight,
        member_count=cluster.member_count,
        representative_book_id=cluster.representative_book_id,
        representative_title=representative_title,
        member_book_ids=cluster.member_book_ids[:MAX_SUMMARY_MEMBERS],
        top_terms=top_terms,
        top_genres=top_genres,
        evidence_summary=_evidence_summary(cluster),
        coherence=cluster.coherence,
    )


def summarize_shelf(
    shelf: ShelfProfile, descriptors: Mapping[int, BookDescriptor], shelf_name: str
) -> ShelfProfileSummary:
    members = [descriptors[book_id] for book_id in shelf.member_book_ids if book_id in descriptors]
    representative = descriptors.get(shelf.representative_book_id)
    top_terms = _top_values(member.tags for member in members)
    top_genres = _top_values(((member.genre,) if member.genre else ()) for member in members)
    return ShelfProfileSummary(
        shelf_id=shelf.shelf_id,
        shelf_name=shelf_name,
        label=build_label(top_terms, top_genres, representative.title if representative else ""),
        member_count=shelf.member_count,
        representative_book_id=shelf.representative_book_id,
        representative_title=representative.title if representative else "",
        top_terms=top_terms,
        top_genres=top_genres,
    )


def build_label(
    top_terms: Sequence[str], top_genres: Sequence[str], representative_title: str
) -> str:
    """A deterministic, human-readable name for an interest (rec-spec §13).

    Preference order, and the reasoning: shared *tags* say the most about
    what a group of books has in common; a shared genre is broader but still
    meaningful; and when members share no vocabulary at all — which happens
    when a coherent interest spans books whose tags were sparse — the
    representative book names it, which is rec-spec §13's own suggested
    fallback.
    """
    if top_terms:
        return " · ".join(top_terms[:3])
    if top_genres:
        return " · ".join(top_genres[:2])
    if representative_title:
        return f'Interest around "{representative_title}"'
    return "Unlabelled interest"


def _top_values(groups: object) -> tuple[str, ...]:
    """Most common values across member books, ties broken alphabetically.

    Alphabetical tie-breaking is what makes a label stable: without it, two
    equally-common tags could swap places between runs and the same reader
    would see their interest renamed.
    """
    counts: dict[str, int] = {}
    for group in groups:  # type: ignore[attr-defined]
        for value in group:
            if not value:
                continue
            counts[value] = counts.get(value, 0) + 1
    if not counts:
        return ()
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    # A term shared by only one book of several describes that book, not the
    # interest — so require support once there is more than one member.
    total_members = max(counts.values())
    if total_members > 1:
        ranked = [item for item in ranked if item[1] > 1] or ranked[:1]
    return tuple(value for value, _ in ranked[:MAX_SUMMARY_TERMS])


def _evidence_summary(cluster: InterestCluster) -> str:
    """Why these books were grouped, in words (rec-spec §13: "Preserve
    enough evidence to answer 'why was this inferred as one interest?'")."""
    sources = ", ".join(cluster.sources) if cluster.sources else "unknown"
    return (
        f"{cluster.member_count} book(s) from {sources}; "
        f"combined evidence weight {cluster.weight:.1f}; "
        f"mean pairwise similarity {cluster.coherence:.2f}"
    )
