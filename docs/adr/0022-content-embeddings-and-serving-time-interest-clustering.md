# ADR-0022: Content embeddings, deterministic book text, and serving-time interest clustering

## Status

Accepted (Recommender Phase R5). Implements ADR-0016 (multi-interest
profiling) and ADR-0018 (offline swappable encoder) within ADR-0014's
artifact boundary and ADR-0021's dependency isolation.

## Context

R5 had to answer three questions the earlier phases could state but not
settle: what text the encoder actually reads, what the embedding artifact
costs, and *where the interest clustering runs*.

The third is the consequential one. rec-spec §12.2 requires inferring
multiple interests per reader from their positive evidence, and that
inference happens when a recommendation batch is built — at serving time.
The obvious implementation imports `scikit-learn`'s
`AgglomerativeClustering`. But scikit-learn is a training-only dependency
(ADR-0018, rec-spec §25 lists it under "Build/training dependencies"), and
ADR-0021 established that the training stack is pruned out of the API
environment entirely.

## Decision

### Interest clustering is pure NumPy, in the recommender package

Average-linkage agglomerative clustering over a cosine similarity matrix,
implemented directly. The input is bounded to ~100 items by rec-spec §12.2,
so the naive O(n³) formulation costs microseconds and is far easier to
verify than a heap-based variant — and it keeps `scikit-learn` off the
request path, matching the precedent set by ALS fold-in in R4.

This is the same reasoning applied a third time: **every runtime
counterpart of a training library is plain NumPy.** ALS fold-in without
`implicit`, neighbour lookup without `scipy`, interest clustering without
`scikit-learn`.

### A threshold, never a K, and an explicit fallback ladder

rec-spec §12.2: "Do not force every user into the same number of
interests." Clusters merge while average-linkage cosine similarity exceeds
`merge_threshold` (0.55) and stop otherwise, so the number of interests is
an *outcome*.

The ladder matters more than the clustering, because most real readers are
sparse:

| Evidence | Strategy | Why |
|---|---|---|
| 0 items | `none` | No semantic profile at all — the caller falls back |
| 1-2 items | `individual_books` | Clustering two books says nothing the books do not |
| ≥3, structure found | `clustered` / `single_cluster` | The intended path |
| ≥3, only singletons | `fallback_centroid` | rec-spec §12.2: do not fabricate cluster structure |

The chosen branch is recorded on the profile rather than inferred, because
"this reader has one interest" and "this reader had too little evidence to
cluster" look identical from outside and mean opposite things.

### Labels are deterministic, from shared vocabulary

rec-spec §13 forbids LLM labelling in V1. A label is the most *shared* tags
among an interest's members, then genres, then rec-spec §13's own fallback
form — `Interest around "The Left Hand of Darkness"`. Two rules keep labels
stable: ties break alphabetically, and a term used by only one member of a
multi-book interest is excluded, because it describes that book rather than
the interest.

Summaries never contain vectors (rec-spec §13), which is also what keeps
recommendation diagnostics from becoming the data dump CLAUDE.md warns of.

### The book text is versioned, and the encoder is not asked to read
everything

Fields in a fixed order with the **description last**, so that encoder
truncation removes description tail rather than title or author. Absent
fields are omitted rather than emitted as dangling labels — ~2,300 catalog
books have no author.

rec-spec §11.2's "do not embed" list is honoured literally: no ratings, no
popularity counts, no ISBNs, no page counts, no ids. Embedding "4.27 average
rating" would let the encoder cluster books by how well they sold.

`TEXT_TEMPLATE_VERSION` and `TAG_CLEANING_VERSION` are recorded in the
artifact manifest, because a change to either changes every vector.

### Shelf tags are cleaned by whole-token matching

The catalog has 173,787 distinct tags, and the most common ones are a
mixture of subject matter (`fiction`, `historical-fiction`) and personal
filing (`to-read`, `books-i-have`, `kindle-books`, `read-in-2011`).
Embedding the second group would cluster books by how people file them.

Matching is on whole tokens, never substrings: `own` must reject
`own-to-read` without touching `downtown`, and `read` must not take
`spreadsheets` with it. On the live catalog this rejects 332,962 of
1,699,225 tag links (19.6%) — reading-log years, ownership, format, wishlist
and challenge-list tags — and the survivors are recognisably thematic.

### 512 tokens and batch 16, as a measured cost decision

Not model limits — Qwen3-Embedding-0.6B accepts 32,768 tokens. Measured on
this catalog: median book text is ~180 tokens and the 90th percentile ~380,
so 512 covers the corpus. Throughput on Apple MPS at 512 tokens: 17.6
books/s at batch 16, 15.0 at batch 32, 11.0 at batch 64. Sustained over
the full catalog the rate is lower than that short-sample benchmark — 16.1
books/s — so a full build takes about 96 minutes.

### The loader refuses an artifact that is not normalized

Retrieval treats the dot product as cosine similarity (rec-spec §11.1), so
an unnormalized artifact would rank by vector magnitude — longer
descriptions first — and look entirely plausible. The manifest must declare
`normalized: true` *and* a deterministic sample of rows must actually be
unit-norm.

The resolved encoder commit hash is recorded when the hub provides one,
because loading by tag records only the tag and will silently mean a
different model later.

## Alternatives considered

- **scikit-learn at serving time** — rejected, as above. It would put a
  training dependency on the request path for forty lines of arithmetic.
- **A fixed K, or K chosen by silhouette score** — rejected by rec-spec
  §12.2. A reader with one coherent taste and a reader with five would both
  be forced into the same shape.
- **One global centroid per reader** — rejected: averaging "medieval
  history" and "space opera" produces a vector describing neither, which is
  the specific failure ADR-0016 exists to avoid.
- **pgvector / FAISS / a vector service** — rejected for now by rec-spec
  §11.1 and §29. Exact search over 92,524 × 512 normalized vectors is one
  matmul; adding retrieval infrastructure before profiling shows a need
  would violate the constraint every prior ADR has held to.
- **Embedding shelf names and descriptions** — deferred. rec-spec §12.1
  explicitly does "not require this in V1", and user-authored shelf names
  need their own cleaning rules to avoid the same bookkeeping problem the
  catalog tags had.
- **Synonym mapping for tags** (`sci-fi` → `science-fiction`) — not done.
  The encoder is semantic and multilingual; it already places the two near
  each other, and a hand-maintained synonym table is a source of silent
  drift the spec does not ask for.
- **Truncating to 256 tokens** to halve build time — rejected. It would cut
  the 90th-percentile description mid-text for a build that runs rarely.

## Consequences

- The content artifact is 181 MB — larger than everything else combined.
  Measured since (plan.md §5n): it costs **427 MB resident**, because the
  loader holds the freshly-read matrix alive while fancy-indexing it into a
  second full-size array, and all six families together come to ~1.0 GB per
  worker. `load_content_artifact(mmap=True)` removes exactly one copy at no
  load-time cost. Whether to make that the default — or to avoid the second
  copy outright — is a decision for R6, which is the first phase to put
  these artifacts on the request path.
- Rebuilding embeddings takes ~96 minutes, so it is the one artifact that
  cannot be casually regenerated. `--limit` exists for development, and the
  `work_id` resolution in ADR-0020 means a re-import does not *invalidate*
  the artifact, only leave new books unembedded — which the profiler
  reports rather than hides.
- Changing the tag rules, the text template or the encoder invalidates every
  vector. All three are versioned in the manifest so the invalidation is
  visible rather than silent.
- `make inspect-recommender-profile USERNAME=<name>` calls the same
  profiling functions as serving, so there is no second implementation to
  drift (rec-spec §13). It needs both the content and item-metadata
  artifacts and says so when they are missing.
- Nothing is wired into serving yet: R6 builds the candidate generators
  that consume these, R8 integrates the pipeline.
