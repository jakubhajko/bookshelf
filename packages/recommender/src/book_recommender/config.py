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

ITEM_METADATA = ArtifactFamily(
    name="item_metadata",
    directory="item_metadata/latest",
    # Title / primary author / top genre from the catalog. The cleaned
    # shelf-tag columns exist in the contract but are unpopulated until the
    # tag cleaner lands in R5.
    preprocessing_version="catalog-fields-v1",
)

#: Families that exist today. ALS, item-item CF and content embeddings join
#: this registry in R4/R5 when their builders exist.
FAMILIES: Mapping[str, ArtifactFamily] = {
    family.name: family for family in (POPULARITY, SOURCE_SIMILARITY, ITEM_METADATA)
}
