# Claude Code Bootstrap Prompt — Bookshelf Recommender Integration

Copy the prompt below into Claude Code **from the repository root** after placing these files in the repository root:

- `CLAUDE.md` (use the updated version supplied with this packet)
- `RECOMMENDER_SPECIFICATION.md`
- `RECOMMENDER_IMPLEMENTATION_PLAN.md`
- this file may remain in the repo as documentation

Do not delete `APP_SPECIFICATION.md`, existing ADRs, or `docs/implementation/plan.md`.

---

## Prompt to give Claude Code

You are integrating the full modular recommender system into the existing Bookshelf repository.

This is a mature codebase. Do **not** redesign it from scratch and do **not** assume the specification's file paths are more authoritative than the live implementation. The specification defines required behavior and architectural intent; inspect the repository to integrate it into the real current structure.

### Read before changing anything

Read, in this order:

1. `CLAUDE.md`
2. `APP_SPECIFICATION.md`
3. `RECOMMENDER_SPECIFICATION.md`
4. `RECOMMENDER_IMPLEMENTATION_PLAN.md`
5. all current ADRs relevant to recommendations, artifacts, persisted batches, deployment and search
6. `docs/implementation/plan.md`

Then inspect the current implementation and `git status`.

Pay special attention to the existing:

- `packages/recommender` contracts/providers/engines/artifacts;
- `FuturePipelineRecommendationEngine` seam;
- recommendation service transaction boundary;
- `FallbackProvider` and popularity engine;
- eligibility/exclusion rules;
- persisted recommendation requests/results/impressions and cursor paging;
- context builder and user/shelf interaction persistence;
- `interaction_events` unused attribution columns;
- frontend recommendation card/detail navigation and actions;
- search submission/suggestions flow;
- `data/processed/books.parquet` and `interactions.parquet`;
- source Goodreads similarity data;
- current Makefile/uv workspace/testing conventions.

### Non-negotiable working method

Implement the recommender according to `RECOMMENDER_IMPLEMENTATION_PLAN.md` **one phase at a time**.

For this session, start with **Phase 0 only**.

Do not opportunistically begin Phase 1 after Phase 0 is complete.

Before edits, give me a concise Phase 0 plan based on what you actually found in the repository. If the code has drifted from the architectural investigation, adapt narrowly and document the divergence rather than forcing obsolete assumptions onto the code.

Do not ask me questions already answered by the specifications. If a small implementation detail is genuinely unspecified, choose the most conservative reversible option consistent with the repository and document it.

Preserve all existing user changes. Do not use destructive git commands. Do not rewrite unrelated modules. Do not auto-commit unless I explicitly ask.

### Architecture that must survive

The existing application/recommender seam is valuable and should be preserved:

- modular monolith;
- React/TypeScript/Vite frontend;
- FastAPI/PostgreSQL/SQLAlchemy backend;
- independent typed `book_recommender` package;
- no FastAPI or ORM imports inside the recommender package;
- services own transactions;
- no open DB transaction during recommender inference;
- artifact-backed recommender runtime;
- provider/engine boundary;
- `InProcessProvider` + `FallbackProvider`;
- app-owned eligibility rules;
- persisted recommendation batches/cursors;
- final engine order is authoritative;
- stable artifact mapping uses `work_id`; never assume PostgreSQL autoincrement `book_id` survives database rebuilds;
- popularity remains a robust fallback;
- no microservice/Redis/Celery/Kafka/vector-database detour.

### Target recommender

The completed implementation must eventually provide:

```text
surface-specific RecommendationRequest
        ↓
5 candidate-generator families
  ALS CF
  item-item CF
  semantic/content (explicit shelves + inferred interests)
  resolved Goodreads/source similarity
  popularity fallback
        ↓
weighted RRF candidate union
        ↓
deterministic feature ranker
        ↓
surface-specific diversity/UX reranker
        ↓
authoritative persisted batch
```

Home, Shelf and Similar Books must use different configurations while sharing the same modular pipeline code.

### User data principles

Do not create one universal interaction score.

Extend the existing raw interaction-event architecture so the project records the high-value missing behavior and provenance:

- intentional `book_opened`;
- short-lived browsing `session_id` separate from auth session;
- recommendation request/surface/rank attribution into open/save/rating/Not-Interested when known;
- meaningful submitted searches and search→book-open attribution;
- shelf membership + save timestamps in recommender context;
- explicit onboarding taste seeds that are neither fake ratings nor fake shelf saves.

Impression-without-open is exposure, not a V1 negative preference.

Do not add dwell time, hover, mouse movement or scroll depth.

### Collaborative design

ALS is trained offline on historical interactions. A live application user is folded into fixed item factors from current durable positive evidence on a fresh recommendation-batch request. Do not globally retrain ALS when one user saves/rates a book.

Item-item CF is also trained offline. User-profile changes change seed books/weights, not the global item-item artifact.

Historical integer users and application UUID users must remain disjoint.

Historical rating `0` is implicit positive and has no timestamp.

### Semantic design

Use a swappable offline text-embedding artifact. V1 default:

- `Qwen/Qwen3-Embedding-0.6B`
- normalized embeddings
- configurable output dimension, default 512
- deterministic versioned text builder using title, author, description, genre and cleaned/bounded useful catalog shelf tags
- no popularity/ISBN/page-count noise in semantic text
- exact batched matrix similarity for the ~92k catalog; no vector DB/FAISS unless profiling later proves necessary

Represent the user with **both**:

1. explicit shelf vectors;
2. inferred interest clusters from positive evidence.

Inferred interests use threshold-based hierarchical/agglomerative cosine clustering rather than a fixed number of clusters. Too little/noisy evidence must fall back gracefully instead of fabricating clusters.

For each inferred interest keep both a weighted centroid (default retrieval query) and a representative medoid.

### Human-inspectable interests are required

Interest inference must be inspectable by a human.

Each inferred cluster should expose deterministic diagnostic information:

- interest ID within profile version;
- deterministic label based on cleaned tags/genres/representative book, not an LLM;
- weight;
- representative/medoid book;
- top terms/tags/genres;
- member books;
- evidence summary.

Add a developer inspection command that uses the exact same profiling implementation as live recommendation, ideally something like:

```text
make inspect-recommender-profile USERNAME=<name>
```

with optional JSON output.

### Fusion/ranking

Use weighted Reciprocal Rank Fusion for V1 candidate union because raw ALS/cosine/graph/popularity scores are not calibrated to the same scale. Preserve all generator provenance and per-source ranks/raw scores.

Build a deterministic/configurable V1 ranker. Do not train a learned engagement ranker until the new open/click attribution data exists in sufficient quantity.

Use stronger diversity/multi-interest coverage on Home, lighter diversity on Shelf, and minimal diversity on Similar Books.

### Cold start

Add skippable onboarding that lets new users select a few books they like. Persist them as explicit taste seeds, not ratings/saves.

Skipped onboarding must still produce a sensible diversified popularity fallback. Similar Books should use the source book even for a cold user.

### Artifact/runtime rules

Training/build code may use processed Parquet/PostgreSQL as appropriate. Serving inference must use immutable context + artifacts.

Prefer compact `.npy`/`.npz` numerical artifacts over huge JSON payloads.

The text encoder is an offline build dependency; do not make the API load a 0.6B transformer to serve recommendations.

Use the existing artifact manifest/model-version/storage patterns and improve them rather than creating a parallel artifact system.

### Quality gate for every phase

Implement tests as part of each phase, not afterward.

Run relevant focused checks during development and the repository quality commands required by `CLAUDE.md`/the phase plan. If an environment limitation prevents a command, document the exact blocker rather than claiming success.

Update `docs/implementation/plan.md` before stopping.

### What to do now

Execute **Phase 0 — Reconcile, baseline and lock architectural decisions** from `RECOMMENDER_IMPLEMENTATION_PLAN.md`.

When Phase 0 is complete, stop and report:

1. architecture/code drift found;
2. files changed;
3. ADR/doc decisions made;
4. commands/tests run and their results;
5. unresolved risks/blockers;
6. the exact next phase, without starting it.
