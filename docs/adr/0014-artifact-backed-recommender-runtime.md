# ADR-0014: Artifact-backed recommender runtime, no database access from the engine

## Status

Accepted (Recommender Phase 0). Extends ADR-0006 and ADR-0007; builds on the
`ArtifactManifest` contract introduced in application Phase 5.

## Context

The five candidate generators need item-level data at inference time —
latent factors, item-item neighbour lists, normalized text embeddings,
source-similarity edges, popularity scores — over a ~92k-book catalog. The
obvious shortcut is to let a generator query PostgreSQL for what it needs.

Three existing constraints rule that out. `packages/recommender` has no
ORM dependency at all (ADR-0006). ADR-0007 makes it a hard ordering
constraint that no database transaction is open during inference. And the
recommender engine runs via `asyncio.to_thread` inside `InProcessProvider`,
where a lazily-issued query would execute on a thread with no session
scope.

There is also a correctness constraint that only shows up across a database
rebuild: PostgreSQL `books.id` is an autoincrement surrogate assigned at
import time. A model trained against one import and served against another
would silently recommend the wrong books — the failure is invisible,
produces plausible-looking output, and corrupts every downstream metric.
The dataset's `work_id` is the stable identity; `books.id` is not.

Phase 0 inspection found the current popularity loader parses
`manifest.json`/`scores.json` inline inside
`modules/recommendations/wiring.py`. That works for one artifact of one
shape. It does not generalize to five model families without accumulating
ad-hoc parsing in application wiring — the wrong layer for it.

## Decision

Runtime recommender inference operates exclusively on (a) the immutable
request/user/surface context the application builds before ending its read
transaction, and (b) artifacts loaded once per process at provider
construction. No generator, ranker or reranker queries PostgreSQL.

Artifact loading moves into the recommender package's artifact layer.
`wiring.py` selects and constructs; it does not parse model file formats.

`work_id` is the durable cross-system item identity. Every artifact carries
the `book_id`/`work_id`/`model_item_index` triple already defined by
`ArtifactItemMapping`, and every artifact records enough metadata to be
reproduced and to be rejected when incompatible: model name, model version,
catalog version, training/creation timestamp, preprocessing/config version,
training-data transform version where relevant, and the file list.

Compatibility is checked at load time against the live catalog version. An
artifact whose item mapping cannot be reconciled with the live catalog is
not served — it degrades to the fallback path rather than serving
plausible-looking wrong books.

Numeric payloads are compact NumPy `.npy`/`.npz` arrays (memory-mapped
where it helps), not large JSON arrays. Offline build code may read
PostgreSQL and processed Parquet freely; that is a different process with
different constraints.

Missing or corrupt artifacts never fail application startup — they
degrade, log structured diagnostics, and leave popularity as the floor.
This is the behavior `_load_popularity_engine` already implements and it
generalizes to the other families.

## Alternatives considered

- **Let generators query PostgreSQL directly** — rejected on all three
  counts above: it would put an ORM dependency in `packages/recommender`,
  reopen a transaction during inference against ADR-0007, and run queries
  on a worker thread with no session scope.
- **Key artifacts on PostgreSQL `book_id`** — rejected. Convenient at
  serving time, silently catastrophic across a re-import, and the failure
  mode is undetectable without exactly the `work_id` mapping this decision
  requires.
- **A vector database, pgvector, or FAISS to hold embeddings** — rejected
  for now (`RECOMMENDER_SPECIFICATION.md` §29). Exact batched matrix
  similarity over ~92k normalized vectors is a single dense matmul; adding
  retrieval infrastructure before profiling shows a need would violate the
  "no premature infrastructure" constraint every prior ADR has held to.
  Revisit only with profiling evidence.
- **Keep per-model parsing in `wiring.py`** — rejected. Five families
  would make application wiring the de facto artifact format registry,
  inverting the module boundary ADR-0002 sets up.
- **Load artifacts lazily on first use rather than at provider
  construction** — deferred, not rejected. Construction-time loading keeps
  first-request latency predictable; whether a large embedding matrix
  should be memory-mapped lazily is a Phase 9 profiling question.

## Consequences

- Every API worker process holds its own copy of the loaded artifacts.
  Memory cost is per-worker, not per-host, and must be measured and
  documented (recommender Phase 9), because it directly bounds how many
  workers a deployment can run.
- Rebuilding the database without rebuilding artifacts is a detectable,
  handled condition rather than silent corruption — but it does mean
  `make import-data` invalidates artifacts, which the artifact build
  commands and documentation must say plainly.
- Offline build code and runtime serving code read the same artifacts
  through the same loaders, so a format change cannot drift between
  writer and reader.
- Training-only dependencies (the text encoder in particular) stay out of
  the API runtime dependency set: the API loads matrices, never models.
