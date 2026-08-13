# ADR-0018: Offline text embeddings with a swappable encoder

## Status

Accepted (Recommender Phase 0). Implements the artifact rules in ADR-0014.

## Context

Semantic retrieval and interest clustering (ADR-0016) need a vector per
book. The catalog is ~92,526 books with titles, authors, descriptions,
genres and Goodreads shelf tags.

The decision that matters is not which model — it is *where the model
runs*. A 0.6B-parameter transformer loaded into each API worker would add
gigabytes of resident memory per worker, seconds to startup, and a GPU/CPU
inference dependency to a request path whose entire budget is ~5 seconds
(`RECOMMENDER_SPECIFICATION.md` §24) — to compute vectors for books that do
not change between imports.

The text fed to the encoder matters as much as the encoder. Embedding
whatever fields are handy produces a space where books cluster by
publication year or ISBN prefix. Goodreads shelf tags in particular are a
mix of genuine thematic signal (`space-opera`, `nordic-noir`) and personal
library bookkeeping (`to-read`, `owned`, `kindle`, `book-club-2014`) — the
latter is pure noise that would cluster books by how other people manage
their reading lists.

## Decision

**Embeddings are built offline, as an artifact.** The API loads a matrix;
it never loads a transformer. The encoder is a build-time dependency,
separated from the API runtime dependency set.

**The encoder is swappable behind a versioned abstraction.** V1 default:
`Qwen/Qwen3-Embedding-0.6B`, output dimension 512 (configurable),
embeddings L2-normalized so cosine similarity is a dot product and
retrieval is one dense matmul. Chosen for strong general retrieval and
clustering quality, multilingual coverage, instruction awareness,
configurable output dimensionality, and a size that fits an offline build
on ordinary hardware.

No Qwen-specific behavior leaks into serving contracts. Artifact metadata
records encoder name, pinned revision where obtainable, embedding
dimension, normalization, prompt/instruction version, and text-template
version — enough to reproduce the artifact and to detect that a stored
vector set was built differently from what the current configuration
expects.

**A deterministic, versioned text builder**, structured:

```text
Title: ...
Author: ...
Genres: ...
Themes/Tags: ...
Description:
...
```

Included: title, primary author, description (the dominant free-text
field), broad genres, and a bounded, cleaned set of catalog shelf tags.

Excluded, deliberately: ratings and popularity counts, ISBNs, page counts,
raw opaque identifiers, and every other numeric quality field. Those are
ranking features (ADR-0017). Embedding them means a semantically unrelated
bestseller sits near another bestseller because both are popular.

Shelf-tag cleaning is deterministic, tested and versioned: bookkeeping,
reading-status and personal-library tags are filtered out, tags are capped
per book, and high-support thematic tags are preferred. Text length is
bounded.

Compact per-book metadata (stable IDs, title, author, top genre, selected
cleaned tags) is stored alongside the vectors, because ADR-0016's
inspection requirement cannot be satisfied from vectors alone.

**Retrieval is exact batched matrix similarity.** No pgvector, no FAISS,
no vector database, no retrieval service. At ~92k × 512 floats the full
catalog is a ~190 MB float32 matrix (less at reduced precision) and a
multi-query search is one matmul. Approximate nearest-neighbour
infrastructure trades exactness and operational simplicity for a speedup
this scale does not need. Revisit only if profiling (recommender Phase 9)
demonstrates a real problem.

## Alternatives considered

- **Embed at request time in the API** — rejected, see Context. Book text
  does not change between imports; recomputing per request spends the
  entire latency budget on a cache-miss-by-design.
- **A smaller/faster encoder (MiniLM-class)** — reasonable, and exactly why
  the encoder is swappable and versioned. Since encoding happens once per
  import rather than per request, build cost is not the binding constraint,
  so V1 defaults to the stronger model. Changing it is a configuration and
  rebuild, not a code change.
- **A hosted embedding API** — rejected. Adds an external network
  dependency, per-token cost, and a non-reproducible artifact (the provider
  can change the model underneath a fixed name) to a local-first project
  (ADR-0009).
- **Embed raw shelf tags without cleaning** — rejected, see Context.
  `to-read` is the single most common Goodreads shelf tag in existence and
  carries no semantic information about the book at all.
- **Include ratings/popularity in the embedded text** — rejected. Pollutes
  the semantic space with a signal that already has a proper home as a
  ranking feature.
- **pgvector / FAISS / a vector database** — rejected at this scale
  (`RECOMMENDER_SPECIFICATION.md` §29), see Decision.

## Consequences

- The embedding matrix is the largest artifact in the system and is loaded
  per API worker (ADR-0014). Its memory footprint is a real deployment
  constraint that must be measured and documented, and it is the strongest
  argument for memory-mapping if profiling shows pressure.
- Re-importing the catalog invalidates embeddings. The build command and
  documentation must state this; artifact/catalog compatibility checking
  (ADR-0014) is what turns a stale artifact into a handled condition
  rather than silently wrong recommendations.
- The text-template version and tag-cleaning rules are part of the
  artifact's identity. Changing either changes the vector space and
  requires a full rebuild — hence both being versioned rather than
  incidental.
- Heavy build dependencies (`sentence-transformers`/transformers stack)
  enter the uv workspace as build/training dependencies only, kept out of
  the API runtime set, and locked through the existing workspace lockfile
  rather than hand-edited.
