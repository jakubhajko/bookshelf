# ADR-0024: Duplicate works are an identity problem, not a similarity problem

## Status

Accepted (Recommender Phase R7). Implements ADR-0017's fusion, ranking and
reranking, and **corrects one of its assumptions**.

## Context

ADR-0017 specifies a reranker that "penalizes semantic near-duplicates",
and R6's live smoke test appeared to hand it a textbook case: the catalog
holds `#58203 'Dune'` (16,541 ratings) and `#67405 'Dune *'` (69 ratings) as
two separate works with two different `work_id`s, and Similar-to-*Dune*
returned the second one. R6 recorded this as risk #112 and stated that
ADR-0017's near-duplicate reranking was the intended answer.

That statement was wrong, and R7's live run is what proved it. Measured on
the real content artifact:

```text
cos('Dune', 'Dune *')        = 0.7246
cos('Dune', 'Dune Messiah')  = 0.8092
```

**The duplicate is less similar to the original than the sequel is.** No
cosine threshold separates them: anything low enough to catch `'Dune *'`
suppresses `'Dune Messiah'`, which on Similar Books is exactly the book a
reader wants.

The cause is not a defect in the encoder. The duplicate row has 69 ratings,
so it carries a much thinner description and far fewer shelf tags, and R5's
text builder faithfully encodes *the text that exists*. The two rows are
near-duplicate in **work identity**; they are genuinely not near-duplicate
in content.

A second problem surfaced in the same run. The reranker compared each
candidate against what it had already **selected** — and on Similar Books
the source book is excluded from the results, so it never entered that set.
Nothing was ever comparing candidates to the book the reader was actually
looking at.

## Decision

### Duplicate control has two independent mechanisms

**Identity**, via `duplicate_key(title, author)`: the title lowercased with
punctuation stripped, plus the author. `'Dune *'` and `'Dune'` collapse to
one key; `'Dune Messiah (Dune Chronicles #2)'` does not. It returns `None`
when either field is empty rather than producing a key that collides on
emptiness — ~2,300 catalog books have no author, and grouping them into one
work would be far worse than missing a duplicate.

**Content**, via the existing cosine threshold: catches a reissue whose
description was copied verbatim, which identity misses when the titles
differ.

Neither subsumes the other, and both are cheap. The tests say so explicitly,
including one that records the measurement above so a later reader does not
"simplify" by deleting the identity check.

### The reranker takes reference books

`RerankContext.reference_book_ids` seeds the duplicate checks with books
that are *present but not selected* — on Similar Books, the source book.

They seed the duplicate checks **only**. They deliberately do not feed the
author or series counters, because rec-spec §19 says not to aggressively
suppress same-author items on Similar Books: the Dune sequels are the right
answer there, and only another *Dune* is not.

### Ranker features are normalized within the batch, not globally

Every feature is put on [0, 1] before weighting, so the weights in
`RankingWeights` are comparable to each other and a person reading the
diagnostics can tell what dominated.

Two normalizations are deliberate rather than incidental:

- **Fusion score against the batch maximum.** Raw RRF scores are tiny
  (`weight / (60 + rank)`) and their absolute size is meaningless; only
  their order within this batch matters.
- **Popularity min-max *within the candidate set*.** Against the whole
  catalog this feature would be near-constant, because every candidate that
  survived retrieval is already far above the catalog median — and a
  constant feature cannot break a tie, which is the only job rec-spec §18
  leaves it.

**Semantic relevance takes the best query, never the mean.** A book that
strongly matches one of a reader's four interests is a good recommendation;
averaging would penalize it for being unrelated to the other three, which is
how ADR-0016's multi-interest profiling would get quietly undone one layer
below where it was built.

## Alternatives considered

- **Lower the cosine threshold until `'Dune *'` is caught** — rejected;
  measured to also catch `'Dune Messiah'`, and every other sequel.
- **Deduplicate at import time** — rejected for R7, and genuinely tempting.
  The rows have distinct `work_id`s from the source data, so merging them is
  a catalog decision with consequences for ratings, shelves and permalinks
  that reach far outside the recommender. Recorded as risk #117 instead.
- **Fuzzy title matching (edit distance, token-set ratio)** — rejected as
  premature. Exact normalized-title-plus-author is cheap, has no threshold
  to tune, and demonstrably fixes the observed case; a fuzzy matcher adds a
  threshold and a new class of false positive to solve a problem nobody has
  yet counted.
- **Normalizing popularity against the catalog** — rejected, see above.
- **Reranking after the engine returns** — rejected by ADR-0017 already;
  engine order is authoritative and persisted (ADR-0006, ADR-0007).

## Consequences

- **Duplicate suppression now depends on the item-metadata artifact.**
  Without it there is no identity check, and the cosine check alone will not
  catch the case that motivated this. That is a real degradation, and it is
  recorded rather than hidden (risk #116).
- **The identity key is exact, so it under-catches.** `'Dune'` and
  `'Dune: 40th Anniversary Edition'` are still two works to it. How many
  such pairs exist in the catalog is unknown — nobody has counted (risk
  #117).
- **The reranker is the pipeline's most expensive stage**, at ~50-80 ms for
  a 20-item batch over ~600 candidates, against ~2 ms for fusion and ranking
  combined. It is greedy and re-scores every remaining candidate at every
  step. Comfortably inside the ~5 s provider budget, but it is where the
  cost is if that ever changes (risk #118).
- **Feature weights are tuned by reasoning, not by evaluation.** No labels
  exist yet — that is the same gate ADR-0017 set for the learned ranker.
  R9's evaluation is where these numbers should get real values.
