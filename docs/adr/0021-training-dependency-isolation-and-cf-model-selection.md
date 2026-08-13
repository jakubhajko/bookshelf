# ADR-0021: Training dependency isolation, and selecting CF models at candidate depth

## Status

Accepted (Recommender Phase R4). Implements ADR-0018's dependency rule and
ADR-0014's artifact boundary for the two collaborative-filtering families.

## Context

R4 is the first phase that trains anything, which forces two decisions the
earlier phases could defer.

**Where the training stack lives.** ALS needs `implicit`; item-item
neighbours need `scipy`. ADR-0018 and CLAUDE.md both say training-only
dependencies must stay out of the API runtime, but until R4 there was
nothing to separate, so the rule had never been tested against a real
dependency.

**How a model configuration gets chosen.** rec-spec §9.1 wants a small
config sweep rather than "one unexplained choice", §10 wants the item-CF
default selected "from offline metrics plus coverage/popularity behavior",
and §23.1 wants a documented per-user holdout. None of that says *which*
metric decides, and the choice turns out to change the answer.

## Decision

### Training dependencies live in a non-default `training` group

`implicit` and `scipy` are declared in `apps/api`'s `[dependency-groups]
training`. `make setup` (`uv sync --all-packages`) does not install them;
`make setup-training` does, and the build targets run under
`uv run --group training`.

The separation is enforced by construction rather than by convention:

- **one module imports them.** `modules/recommendations/cf_training.py` is
  the only file in the repository that imports `implicit` or `scipy`. The
  build CLIs import it; nothing on a request path does.
- **every runtime counterpart is plain NumPy.** ALS fold-in solves against
  fixed item factors with `numpy.linalg.solve`; neighbour lookup is an array
  slice. The API loads matrices, it never trains.
- **two tests fail if the stack leaks** into either package's runtime
  dependency set, and `mypy` is configured to typecheck `cf_training.py`
  *without* the group installed, so the default gate cannot start silently
  depending on it.

Verified rather than assumed: `uv sync --all-packages` prunes `implicit`,
`scipy`, `threadpoolctl` and `tqdm` back out of the environment, and the
API still starts and serves.

### Historical user factors are not persisted

rec-spec §9.1 calls them "optional at serving time". They are excluded
outright. 83,200 Book-Crossing user vectors describe people who are not
application users (rec-spec §7.2), and an artifact that shipped them would
put data in every API worker that nothing may legitimately join to. The
trainer keeps them in memory for evaluation and drops them on write; the
artifact directory contains `manifest.json`, `mapping.npz` and
`item_factors.npy` and nothing else.

### Sweeps select at the deepest evaluated cutoff, not the shallowest

`SELECTION_K = max(EVALUATION_K_VALUES) = 50`. All cutoffs are reported;
NDCG@50 decides.

The reasoning is architectural rather than statistical. These are
**candidate generators**, not the final ranker: ADR-0017 fuses several of
them with weighted RRF and a deterministic ranker orders the result. A
generator's job is to get relevant items into a deep candidate pool in a
sensible rank order. Its NDCG@10 measures a stage it is not responsible for.

This changed a real decision. On the live dataset:

| item-CF variant | NDCG@10 | recall@50 | NDCG@50 | coverage | Gini |
|---|---|---|---|---|---|
| cosine-k100 | **0.0215** | 0.0347 | 0.0241 | 0.399 | 0.577 |
| bm25-k100 | 0.0208 | **0.0420** | **0.0258** | **0.547** | **0.374** |

Selecting at @10 ships cosine on a 3% edge. Selecting at @50 ships BM25,
which is 21% better at candidate depth, covers 37% more of the catalog and
is far less concentrated on popular books — which is also what rec-spec
§10's "plus coverage/popularity behavior" points at. For ALS the two
criteria agree (f128 wins both), so this is not a rule invented to justify
a preferred outcome.

### BM25's IDF term is deliberately not applied

Found while testing, and worth recording because the obvious implementation
is silently inert. BM25's IDF is a *per-item* scalar, and item-item cosine
L2-normalizes each item vector before comparing. Normalization cancels any
scalar multiple exactly, so multiplying item *i*'s column by `idf[i]` would
be arithmetic with no effect that reads like popularity correction.

What "BM25" means here is the two terms that do survive normalization:
`k1` saturation, and `b` user-length normalization — a reader with 500
books provides weaker per-book evidence than one with 5. That is the
popularity correction, expressed on the user side, and it is what produces
the coverage and Gini improvements in the table above.

## Alternatives considered

- **Put the training stack in the main dependency set** — rejected by
  ADR-0018. It would add `torch`-adjacent weight to every API worker for
  code the request path never calls.
- **A separate training package in the workspace** — deferred. A dependency
  group achieves the isolation with no new package boundary to maintain;
  revisit if training code grows past a couple of modules.
- **Persist historical user factors for warm-starting fold-in** — rejected.
  Live users are not historical users, so there is no user to warm-start
  from, and the fold-in solve is 6 ms over 92k items.
- **Train negative-confidence ALS on explicit ratings 1–5** — rejected for
  V1 by rec-spec §7.2 ("Do not force negative-confidence ALS training in V1
  merely because the library supports it"). Those 43,593 rows are dropped
  and counted. A positive-only baseline is the thing to beat first.
- **Select on Recall@50 instead of NDCG@50** — rejected as slightly wrong
  for the same architectural reason: RRF consumes *rank*, so position
  inside the candidate list matters and a presence-only metric ignores it.
  It would also have changed the ALS winner to f64 on a 0.0001 margin,
  which is noise.
- **Select on a blended accuracy/coverage score** — rejected as premature.
  A weighted blend needs weights, and there is no evidence yet for what they
  should be. Coverage and Gini are reported next to the accuracy numbers and
  read by a human; R9's evaluation work is where a composite could earn its
  place.

## Consequences

- Running the model builders needs an explicit `make setup-training`. This
  is a documented extra step, and the failure mode when it is skipped is an
  immediate `ImportError` from the CLI, not a subtly degraded artifact.
- Per-worker memory rises substantially once R6 loads these: ALS factors are
  45 MB on disk and the item-CF neighbour graph 36 MB, measuring ~240 MB
  resident with all five families loaded, against 77 MB for the three R3
  families. ADR-0014 already notes that per-worker artifact memory bounds
  deployment density; this is the phase that made it material, and R9's
  profiling now has a real number to work against.
- The shipped ALS configuration is `factors=128, regularization=0.05,
  iterations=20` and item-CF is `bm25, top_k=100`, both recorded in their
  manifests along with `selected_by`, so a later rebuild that picks
  differently is visible rather than silent.
- Evaluation reports accumulate one JSON + one text file per build under
  `data/artifacts/evaluation/`. They are deliberately outside the served
  artifact directories (rec-spec §23.1) and are a build history, not state.
