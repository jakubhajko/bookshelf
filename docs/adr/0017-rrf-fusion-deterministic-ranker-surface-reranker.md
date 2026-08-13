# ADR-0017: Weighted RRF union, deterministic V1 ranker, surface-specific reranker

## Status

Accepted (Recommender Phase 0).

## Context

Five candidate generators return five ranked lists that must become one
ordered batch of 60. Their scores are not comparable: ALS returns an
uncalibrated dot product of latent factors, semantic retrieval returns
cosine similarity in [-1, 1], item-item CF returns a similarity whose scale
depends on the chosen weighting, the source-similarity graph returns edge
ranks with no score at all, and popularity returns a Bayesian-shrunk mean
rating. Normalizing these onto a shared scale (min-max, z-score) requires
assuming a distribution shape none of them actually share, and the
resulting weights would encode that wrong assumption invisibly.

Ranking has a different problem: there is no training data. A learned
engagement ranker needs click/open labels with attribution, and ADR-0015
is the decision to *start collecting* them. Training a ranker now would
mean training on impressions-as-labels — the exact mistake ADR-0015
rejects — or on a few hundred rows.

Reranking has a third problem: the right amount of diversity is a property
of the surface, not the model. Aggressive diversity is correct on Home and
actively harmful on Similar Books, where a reader asking "what's like this
book" and receiving deliberately dissimilar books has been failed.

## Decision

**Union by weighted Reciprocal Rank Fusion.** For candidate `i`:

```text
fusion_score(i) = Σ_g weight(surface, g) / (rrf_k + rank_g(i))
```

Ranks are 1-based, consistently. `rrf_k` defaults to ~60 and is
centralized and tunable. RRF consumes only *rank*, so it is immune to the
scale-incomparability problem entirely, and it naturally rewards candidates
that several independent generators agree on.

Deduplication is by canonical `book_id` and must not lose provenance. Each
surviving candidate retains every contributing source, its rank within that
source, its raw score from that source, that source's RRF contribution, and
the total. Generator quotas and RRF weights are *surface configuration*,
never constants inside a generator.

**A deterministic, interpretable V1 ranker** behind a clean ranker
interface, so a learned model can replace it later without touching the
pipeline. Features are interpretable and configurably weighted: fusion
score, count of independent agreeing generators, generator-specific
relevance, semantic relevance to the surface's query profile, collaborative
relevance, popularity/quality prior, relationship to strong positive
evidence, explicit and semantic negative evidence, seed recency, and
surface coherence.

Popularity is a feature, never the dominant personalization term — a feed
that ranks by popularity with a personalization garnish is not personalized,
it just looks busy.

**No learned engagement ranker until the attribution data from ADR-0015
exists in sufficient quantity.** This is a gate, not a preference.

**A deterministic greedy/MMR-like reranker inside the engine**, before the
authoritative order leaves `packages/recommender`. It penalizes semantic
near-duplicates, repeated authors, detectable repeated series, excessive
concentration in one inferred interest, and excessive concentration from
one candidate source; it rewards coverage of multiple strong interests and
reserves a small controlled exploration allowance. All tunables live in
surface configuration.

Surface strength is deliberately different:

| Surface | Diversity | What dominates |
|---|---|---|
| Home | strongest, plus small controlled exploration | broad multi-interest discovery |
| Shelf | light/moderate | coherence with the target shelf |
| Similar | minimal | relevance to the source book |

Exploration is a reranking policy, not popularity. Conflating the two makes
"exploration" mean "show more bestsellers."

Reasons stay truthful: a reason code must correspond to evidence that
materially contributed. `candidate_sources` stays plural through the
pipeline and into persistence.

## Alternatives considered

- **Score normalization then weighted sum** — rejected, see Context.
  Requires distributional assumptions the generators do not satisfy, and
  hides that assumption inside tuned weights.
- **Unweighted RRF** — rejected. It would give the popularity fallback the
  same influence as ALS on Home, and give global personalization the same
  influence as the source graph on Similar. Per-surface weights are the
  main mechanism by which the three surfaces differ.
- **Train a learned ranker now** — rejected. No labels. Training on
  impressions would encode exposure as preference (ADR-0015).
- **One shared set of weights for all three surfaces** — rejected. It is
  the specific thing that would turn Similar Books into "more books you may
  like," which is a different, worse product.
- **Rerank in the API service after the engine returns** — rejected.
  ADR-0006 and ADR-0007 make engine order authoritative and persist it;
  re-sorting downstream would mean the persisted batch and the served
  order disagree, and the algorithm would live in a service (forbidden).
- **Learned/neural reranking** — rejected for V1, same gate as the ranker.

## Consequences

- Per-candidate provenance is richer than the current `candidate_sources`
  list of strings. It must fit within the existing
  `recommendation_results` model without putting a large diagnostics blob
  on all 60 rows of every batch by default — compact by default,
  feature-flagged when full detail is needed.
- Surface configuration becomes a real, typed, tested artifact of the
  system. "The surfaces genuinely differ" is a testable property, and is
  tested.
- Final order must be deterministic for a fixed request, profile,
  artifact set and configuration. Non-determinism here would make the
  persisted batch unreproducible and every offline evaluation unstable.
- `rrf_k` and the per-surface weights are the primary tuning surface for
  feed quality. They are centralized precisely so tuning does not become
  a hunt through five generator implementations.
