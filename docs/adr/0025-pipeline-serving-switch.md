# ADR-0025: Serving the pipeline — composite model version, artifact-optional startup

## Status

Accepted (Recommender Phase R8). Fills the seam ADR-0006 and ADR-0007
reserved; consumes ADR-0023's generators and ADR-0017/ADR-0024's
fusion, ranking and reranking.

## Context

R8 makes the funnel the served path. Three questions had no answer yet, and
all three only become real once something is actually serving.

**What is the model version of a batch produced by six artifacts?**
`recommendation_requests.model_version` is a single string used to identify
what produced a batch, and until R8 the pipeline had exactly one artifact.
The obvious shortcut — reuse popularity's version — puts an authoritative
looking timestamp in the column that is wrong about five sixths of what
actually ran.

**Where does profile building live?** `build_semantic_profile` sat in
`apps/api` while only the inspection CLI used it. The engine needs it per
request, and an engine inside `packages/recommender` cannot import from
`apps/api`.

**What should startup do when an artifact is missing?** The pipeline has six
of them and rec-spec §27 requires degradation, but "degrade" had never been
tested against a process that has to boot.

## Decision

### `model_version` is a digest over every contributing artifact version

`pipeline-<sha256[:12]>` over the sorted `family=version` pairs of the
artifacts actually loaded, with the full mapping carried in batch
diagnostics.

Deterministic and order-independent, so two workers loading the same
artifacts report the same version; and *any* rebuild changes it, which is
the property that matters — two batches built from different artifacts must
never look identical in the persisted record.

### Semantic profiling moved into `packages/recommender`

To `book_recommender/profiling/semantic.py`, unchanged. The module never
imported FastAPI or SQLAlchemy, which is what made it movable at all.

This strengthens rec-spec §13 rather than weakening it: "the inspection path
must reuse the **same profiling code** used by the live recommender" is now
true by construction, because the CLI and the engine call the same function
and there is nowhere else the clustering could live.

### Every artifact is optional at startup; the process always boots

Each family loads through one helper that logs and returns `None` on
failure. A generator constructed with `None` reports `NO_ARTIFACT` rather
than being silently absent, so the degradation shows up in batch
diagnostics instead of looking like an empty result.

A process that refuses to boot because one artifact is stale is strictly
worse than one that serves popularity while somebody rebuilds it.

### Content and ALS are memory-mapped in serving

`mmap=True` for the two large matrices. Measured in R5: the content
artifact costs 427 MB resident for a 181 MB file because the loader holds
the raw read alive while indexing it, and mmap removes exactly one copy at
no load-time cost. Per-worker footprint is the binding constraint (risk
#106), not latency.

### The engine owns the source-book exclusion

"Do not recommend the book being viewed" is a product rule about Similar
Books, not a property of any retrieval mechanism, so the engine unions it
into the exclusion set rather than each generator knowing about it.

### `future_pipeline` is deleted, not left behind

The placeholder raised on every call to reserve this seam. The seam is
filled, so it is gone rather than kept as unreachable code still claiming
nothing is implemented. The settings value is now `pipeline`.

## Alternatives considered

- **Popularity's version as the batch version** — rejected, see Context.
- **A concatenated version string** (`als=…;content=…;…`) — rejected: it
  does not fit a column meant to be compared, and the same information is
  in diagnostics where it is readable.
- **Failing startup on a missing artifact** — rejected by rec-spec §27, and
  it would make a stale artifact an outage.
- **Leaving profile building in `apps/api` and passing the profile through
  the engine request** — rejected. It would put derived inference state in
  the request contract and let the application decide when profiling
  happens, which is the split ADR-0016 exists to prevent.
- **Reason prose per surface** — not needed. The codes already distinguish
  what the reader is being told; the prose maps one-to-one.

## Consequences

- **The provider is built lazily, on the first request that needs it**, not
  at startup — that was already true and R8 did not change it, but R8 made
  it expensive: the first recommendation request after a boot pays ~1 s of
  artifact loading (risk #121).
- **Reason prose is now load-bearing and was wrong.** R8's live smoke test
  found `SEMANTIC_QUERY_MATCH` rendering as "Matches your search" to a
  reader who had only completed onboarding. It is now "Based on your
  interests", and a test asserts the prose cannot claim evidence its code
  does not carry.
- Ten profiling tests moved from `apps/api` to `packages/recommender` with
  the module, so the suite counts shift accordingly.
- `RECOMMENDATION_PROVIDER` still defaults to `mock`. Switching the default
  is a deployment decision, and the implementation plan asks for it only
  "after all required artifacts and tests are ready".
