# ADR-0026: Item-item CF edges need co-occurrence support, and accuracy beats coverage when only one generator supplies behaviour

## Status

Accepted (Recommender Phase R9). Extends ADR-0021's CF model selection and
**corrects a prediction made in R6 and repeated in R7**.

## Context

R6 recorded risk #111: 788,772 of the item-CF artifact's 7,606,357 edges
(10.37%) had a similarity of exactly 1.0, so aggregation landed large
candidate groups on an identical score and the `book_id` tiebreak ordered
them. Because RRF reads rank and nothing else (ADR-0017), those ranks
entered fusion as though they were evidence. The visible symptom was
`"New Treasury of Children's Poetry"` reaching rank 6 of a Dune reader's
Home feed.

R6 predicted the fix: "a better aggregation tiebreak in R4's
`candidates_from_seeds` — agreement count, or a similarity floor". R9
measured that prediction and it is wrong, twice over.

**The aggregation cannot fix it.** On the live reader the dominant tie
group was 74 candidates, all reached from a *single* seed's neighbour row.
Agreement count is therefore uniformly 1 across the group, and position
within the row is the very ordering being complained about — the builder
had already written the row in ascending column index.

**Support cannot break the tie either.** Cosine is exactly 1.0 only when two
items have identical reader vectors, so every member of such a group has
identical co-occurrence support *by construction*. Sampling the live matrix
confirmed it and revealed what the number actually means:

```text
item 8465:  1 reader,  71 neighbours at cos=1.0, support uniformly 1
item 91736: 1 reader, 167 neighbours at cos=1.0, support uniformly 1
item 35889: 1 reader, 228 neighbours at cos=1.0, support uniformly 1
```

A cosine of 1.0 is not a strong pair. It is **one reader who owned both
books, and nobody else who owned either**. BM25 cannot discount it, because
the match is structurally perfect — the two items really do have identical
readership. It is a coincidence in one library, presented to the funnel as
the strongest possible collaborative signal.

## Decision

### 1. Filter item-CF edges by co-occurrence support

`ItemCfConfig` gains `min_support`: the minimum number of readers who
touched **both** items for an edge to be kept. Filtering happens in
`train_item_neighbors` before top-K selection, so a row whose strongest
edges are all coincidences keeps its next hundred real ones instead of
coming back short.

The threshold is chosen by the offline sweep on held-out data, not asserted.
`ITEM_CF_SWEEP` covers 1 (v1's behaviour), 2 and 3.

### 2. Ship `min_support = 3`, accepting a large coverage loss

The sweep is unusually clear, and unusually conflicted:

| config | ndcg@50 | recall@50 | catalog coverage | popularity gini |
|---|---|---|---|---|
| bm25-k100-s1 (v1) | 0.0258 | 0.0420 | 0.547 | 0.374 |
| bm25-k100-s2 | 0.0450 | 0.0733 | 0.325 | 0.456 |
| bm25-k100-s3 | **0.0565** | **0.0944** | 0.194 | 0.511 |

Accuracy more than doubles. Catalog coverage falls by two thirds and
popularity concentration rises by a third. This is the first time rec-spec
§10's two selection criteria — offline metrics, and coverage/popularity
behaviour — have pointed in opposite directions, and ADR-0021's rule
(select on NDCG@`SELECTION_K`) alone should not decide something this
lopsided.

**The tiebreaker is what item-CF is for.** Four other generators supply
breadth — the semantic generator alone spans the entire catalog, and
popularity covers the head — while only item-CF supplies "readers who liked
this also liked that". Trustworthy behavioural evidence beats broad
behavioural evidence when breadth is already covered elsewhere, and RRF
rewards *agreement*, which noisy candidates cannot earn.

That reasoning was then checked end to end rather than left as an argument
(plan.md §5s). On the live reader:

- Home's largest item-CF tie group fell from **74 to 2**, and distinct
  scores among 150 candidates rose from 57 to 149.
- Cross-generator agreement rose from **12.4x to 19.5x** chance on Home and
  from 11.3x to 26.9x on Shelf.
- `"New Treasury of Children's Poetry"` left the feed; every book in Home's
  top six is now confirmed by two or three independent generators.
- Every surface still fills 60/60 — including Similar Books for a source
  book with a single rating, where item-CF and the source graph both return
  nothing and semantic plus popularity carry the batch.

### 3. Keep an honest tiebreak in the runtime aggregation

`candidates_from_seeds` now orders by score, then **agreement** (how many
seeds reached the candidate), then **neighbour position**, then `book_id`.
This is not what fixed risk #111 and the code says so; it handles the
multi-seed ties that remain, and it removes catalog insertion order as a
load-bearing signal anywhere in the path.

### 4. `preprocessing_version` becomes `item-cf-topk-v2`

The similarity *values* are unchanged. What changed is which edges exist and
what a row position means, and that is exactly the distinction
`preprocessing_version` exists to record: an artifact built before this is
not comparable to one built after.

## Consequences

**A rebuild is mandatory.** A v1 artifact no longer matches the declared
preprocessing version. `make build-item-cf` takes ~2.5 minutes.

**67% of the catalog has no item-CF neighbours** (30,599 items of 92,524
have a row). Long-tail books are served by the semantic and source-graph
generators, which was already true for the source graph and is measured, not
assumed. If a later surface depends on item-CF specifically, this is the
number to check first.

**The support product doubles the sparse matrix multiplication** in the
builder. Measured cost: the full sweep of four configurations, including
held-out evaluation of each, runs in ~2.5 minutes.

**This does not license threshold-tuning elsewhere.** ADR-0024 rejected
fuzzy duplicate matching because it added a threshold to fix a problem of
unmeasured size; `min_support` is admissible because the problem was
measured first, the threshold is selected on held-out data, and the
alternative values remain in the sweep so the choice can be revisited.
