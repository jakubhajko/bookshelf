# Bookshelf — Recommender Implementation Plan

## Purpose

This is the execution plan for `RECOMMENDER_SPECIFICATION.md`.

Claude Code must implement **one phase at a time**. Each phase must leave the repository in a valid, tested, resumable state. Do not merge phases merely because the code is nearby.

At the start of every phase:

1. read root `CLAUDE.md`;
2. read `RECOMMENDER_SPECIFICATION.md`;
3. read this file;
4. inspect `docs/implementation/plan.md` and relevant ADRs;
5. inspect the current implementation instead of assuming the architectural investigation is still exact;
6. state the phase scope and any verified divergence from the specification.

At the end of every phase:

- run the most relevant focused tests while developing;
- run `make test`, `make lint`, and `make typecheck` unless a documented environment limitation prevents it;
- run migration/API-client/e2e commands when the phase changes those areas;
- update `docs/implementation/plan.md` with completed work, risks, commands run, failures and remaining items;
- add/update ADRs for architectural decisions;
- summarize changed files;
- do **not** claim a phase complete if required checks fail;
- do not automatically git commit unless explicitly asked.

---

# Phase 0 — Reconcile, baseline and lock architectural decisions

## Goal

Prepare the repository for recommender implementation without changing recommendation behavior yet.

## Tasks

- Read the existing recommender boundary, provider/engine contracts, `FuturePipelineRecommendationEngine`, artifact code, recommendation services, eligibility, persistence, context builder, interaction events, shelves, search, frontend recommendation cards, and current settings.
- Verify the codebase still matches the investigation summarized in `RECOMMENDER_SPECIFICATION.md`.
- Identify any uncommitted user changes and preserve them.
- Update/add ADRs for the decisions that materially change the previous architecture/scope:
  - the final modular recommender funnel is now in scope;
  - artifact-backed runtime item data, no DB access from the recommender engine;
  - raw-event + attribution approach;
  - multi-interest semantic profiling using explicit shelves + inferred clusters;
  - weighted RRF + deterministic V1 ranker + surface-specific reranker;
  - offline text embeddings with swappable encoder;
  - cold-start taste seeds are domain state, not fake ratings/saves.
- Reconcile root docs so no active instruction still says “no final recommendation funnel yet.”
- Add a phase checklist to `docs/implementation/plan.md`.
- Do not implement models in this phase.

## Acceptance

- Architecture contradictions are removed/documented.
- Existing tests still pass.
- No recommendation behavior changes.

---

# Phase 1 — Interaction instrumentation, attribution and impression correctness

## Goal

Create reliable raw behavioral data before implementing recommenders that will later depend on it.

## Backend

- Extend `interaction_events` write plumbing so existing nullable attribution fields can actually be populated:
  - `surface`
  - `session_id`
  - `recommendation_request_id`
  - `search_query_id`
  - `source_book_id`
  - `rank_position`
- Add `book_opened` event type.
- Introduce a shared typed optional `InteractionAttribution` request schema/domain shape rather than repeating loose fields.
- Add a dedicated authenticated event write endpoint/service for intentional `book_opened` events. Normal GET book detail remains side-effect free.
- Propagate optional attribution into save/rating/Not-Interested events when supplied.
- Populate `shelf_books.source_surface` when a save source is known, without changing shelf-membership semantics.
- Add meaningful submitted-search persistence. Prefer an explicit `search_queries` domain table and POST/write endpoint rather than side effects in debounced GET search.
- Support search-query → book-open attribution.
- Make recommendation-impression writes idempotent for repeated persisted-page/cursor reads.
- Add retention/cleanup considerations to docs for recommendation request/result/impression data, but do not add a background-job stack.

## Frontend

- Add one browsing-session utility/hook:
  - UUID in `sessionStorage`;
  - rotate after ~30 minutes inactivity;
  - no reuse of auth `sid`.
- Introduce one reusable frontend `RecommendationAttribution`/interaction context type.
- Preserve recommendation `request_id`, `surface`, and rank when opening a recommendation card.
- Fire best-effort `book_opened` event on intentional book detail open without blocking navigation.
- Ensure direct save/rate/Not-Interested actions from recommendation cards/details pass attribution when known.
- Log only submitted/committed search queries, not every suggestion request.
- Preserve `search_query_id` while opening a search result.

## Tests

- duplicate recommendation cursor/page fetch is idempotent;
- `book_opened` writes correct raw fields;
- attributed save/rating is linked to request/rank/session;
- unattributed direct actions still work;
- search suggestions do not create search-query rows;
- submitted search does;
- search-result open links to query;
- browsing session rotates as specified.

## Acceptance

The app can answer: “what was shown?”, “what did the user intentionally open?”, and “which recommendation/search caused the open/save/rating when known?”

---

# Phase 2 — Rich user context, profile version and cold-start taste seeds

## Goal

Make the request context preserve the preference structure that the candidate generators need.

## Context work

- Add immutable per-shelf saved-book snapshots with `book_id`, `shelf_id`, `added_at`.
- Keep convenient existing global `saved_book_ids` for eligibility.
- Preserve useful recent-event fields rather than dropping shelf/session/attribution context.
- Add onboarding taste seeds to `UserContext`.
- Implement deterministic long-term `profile_version` based on durable preference state:
  - ratings;
  - current shelf memberships/timestamps as appropriate;
  - Not Interested state;
  - onboarding taste seeds.
- Passive recommendation impressions must not invalidate long-term profile version.
- Set documented bounds/truncation for context components.

## Taste-seed backend

- Add explicit `user_taste_seeds` state (or an equally clean domain-neutral representation after inspecting repository conventions).
- Store selected book, user, selected timestamp, and source (`onboarding` initially).
- Add raw set/remove events if consistent with the event-log model.
- Do not turn taste seeds into ratings or shelf memberships.
- Provide endpoints/services to read/update onboarding selections.

## Frontend backend contract only

- Generate/update OpenAPI client types if API changes.
- Full onboarding UI may wait until Phase 8, but backend/context behavior must be complete and tested now.

## Tests

- same book may exist on multiple shelves and all memberships survive context construction;
- save timestamp survives;
- profile version deterministic;
- long-term preference mutation changes it;
- passive impression does not;
- taste seed does not imply rating/shelf state;
- existing eligibility/domain rules still pass.

---

# Phase 3 — Artifact substrate, data validation and source-similarity export

## Goal

Create robust artifact loaders/build primitives before training large models.

## Tasks

- Refactor artifact loading so new model types do not require ad-hoc parsing in application wiring.
- Preserve `ArtifactManifest` and stable three-way mapping.
- Add catalog-version compatibility validation and safe degradation.
- Build a reusable mapping validator:
  - `work_id` is durable;
  - PostgreSQL `book_id` is runtime-local;
  - unresolved processed interactions are dropped and reported;
  - historical user IDs never join application users.
- Add compact numerical artifact helpers (`.npy`/`.npz`, optional memory mapping) with safe path handling.
- Export resolved Goodreads/source similarity rows to `source_similarity` artifact.
- Validate every exported source edge resolves to active catalog items.
- Create runtime source-similarity artifact loader.
- Add compact item metadata/features artifact needed for diagnostics/ranking, including stable IDs, title, author, broad genre, and selected cleaned tags once tag cleaning exists; if tag cleaning belongs more naturally in Phase 5, create the artifact contract now and fill it there.
- Add Make/CLI entry points in repository style for artifact builds.

## Tests

- incompatible catalog version rejected/degraded;
- malformed mapping rejected;
- path traversal protections remain intact;
- source graph contains catalog-only IDs;
- deterministic artifact build given same input/config;
- recommender package still has no ORM/FastAPI imports.

---

# Phase 4 — Collaborative-filtering artifacts: ALS + item-item

## Goal

Build, evaluate, serialize and load both collaborative candidate sources.

## Dependencies

Use established numerical libraries and the uv workspace. Keep training-only heaviness separated from API runtime where practical.

## Shared interaction transform

- Read `data/processed/interactions.parquet`.
- Validate schema rather than assuming it.
- Map `work_id` to active catalog items.
- Apply a versioned conservative positive-preference transform from `RECOMMENDER_SPECIFICATION.md`.
- Report counts dropped/used by rating bucket and mapping status.
- Do not invent timestamps.

## ALS

- Train implicit-feedback ALS.
- Sweep a small reasonable config grid if compute permits (e.g. factor count/regularization) rather than hard-coding one unexplained choice.
- Use per-user holdout evaluation because no timestamps exist.
- Persist at least item factors, mapping and training configuration.
- Implement runtime live-user fold-in/recalculation from current durable app-user evidence.
- Global ALS retraining is offline only.
- Fresh recommendation batch recomputes user factor initially; design cacheability via `profile_version` but do not add complex cache infra.

## Item-item CF

- Evaluate at least a simple cosine baseline and a popularity-aware TF-IDF/BM25 nearest-neighbour variant if practical.
- Select/document V1 default from offline metrics plus coverage/popularity behavior.
- Persist top-K item neighbours compactly.
- Runtime generator seeds from current positive items; no retraining on user mutation.

## Offline evaluation

Produce a machine-readable and human-readable evaluation report with at least:

- Recall@K
- NDCG@K
- Precision/MAP where practical
- catalog coverage
- popularity concentration
- config used

## Tests

- fold-in factor changes after meaningful profile change;
- item factors themselves do not retrain on live mutation;
- historical/application users remain disjoint;
- neighbour artifacts deterministic for fixed config;
- candidate retrieval respects exclusion sets.

---

# Phase 5 — Content embeddings, multi-interest profiling and human inspection

## Goal

Build the semantic item space and the user-interest profiler.

## Offline content builder

- Implement deterministic versioned book-text construction.
- Include title, primary author, description, broad genres, and selected useful catalog shelf tags.
- Implement tested shelf-tag cleanup/filtering; do not embed personal/read-status bookkeeping tags.
- Cap tags/text length sensibly.
- Default encoder `Qwen/Qwen3-Embedding-0.6B`, output dimension 512, normalized embeddings.
- Make encoder name/revision/dimension/instruction/template version configurable and recorded in artifact metadata.
- Embedding build must be offline; API runtime must not load the transformer model.
- Save normalized embeddings in a compact exact-search-friendly artifact.
- Save compact metadata required for interest inspection/ranking.

## Semantic retrieval primitive

- Load embeddings once per process.
- Support exact batched dot-product retrieval for one or many query vectors.
- Do not introduce vector DB/FAISS yet.
- Exclusion filtering must be efficient.

## Explicit shelf profiles

- Compute weighted normalized shelf vectors from member-book embeddings.
- Preserve one vector/query per shelf on Home where useful.
- Target shelf dominates Shelf surface.

## Inferred interests

- Implement a pure `InterestProfiler` in recommender package.
- Use normalized embeddings + agglomerative/hierarchical cosine clustering with threshold, not fixed K.
- Bound input to strongest/recent meaningful positive items.
- Implement fallbacks for 0, 1–2, coherent single cluster, and noisy/singleton outcomes.
- Default retrieval query = weighted centroid.
- Compute medoid representative.
- Keep centroid-vs-medoid strategy configurable.

## Human inspectability

For every interest cluster generate deterministic:

- interest ID within profile version;
- human label;
- weight;
- member count;
- representative/medoid book;
- member books;
- top cleaned tags/terms;
- top genres;
- evidence/source summary.

No LLM labeling in V1.

Add developer command such as:

```text
make inspect-recommender-profile USERNAME=<name>
```

and ideally `--json`.

It must call the same `InterestProfiler` used in serving.

## Evaluation/inspection

- semantic nearest-neighbour samples;
- Goodreads-source-edge overlap proxy;
- clustering sanity tests;
- human-readable profile output for seeded demo users.

---

# Phase 6 — Candidate-generator framework and five generators

## Goal

Introduce the reusable generator layer and implement the five agreed candidate families.

## Framework

- Add structural typed `CandidateGenerator` protocol in recommender package.
- Add candidate result type with `book_id`, raw score, generator rank, provenance, compact diagnostics.
- Centralize generator IDs/names.
- Keep generators artifact/context only; no DB access.
- Provide deterministic behavior for fixed request/context/artifacts/config.

## Implement

1. `ALSCandidateGenerator`
2. `ItemItemCFCandidateGenerator`
3. `SemanticCandidateGenerator`
   - can execute multiple query strategies/provenance:
     - inferred interest cluster;
     - explicit shelf profile;
     - target shelf;
     - source book;
     - global fallback where appropriate
4. `SourceSimilarityCandidateGenerator`
5. `PopularityCandidateGenerator` adapter/reuse of existing popularity engine logic

## Important

Do not implement session sequence modeling.

Generators should over-retrieve according to surface config so downstream fusion/ranking has a useful pool.

## Tests

Each generator independently:

- deterministic;
- excludes hard/session exclusions;
- handles empty profile/artifact gracefully;
- reports provenance;
- works on the intended surfaces;
- does not return duplicate books internally.

---

# Phase 7 — Surface config, weighted RRF, deterministic ranking and UX reranking

## Goal

Turn candidate lists into a final high-quality ordered batch.

## Surface configuration

Create typed config for Home, Shelf and Similar with:

- enabled generators;
- candidate quota per generator/query strategy;
- RRF weights;
- signal weights;
- ranking feature weights;
- reranking parameters;
- cold-start/fallback behavior.

Implement the priorities from `RECOMMENDER_SPECIFICATION.md` rather than sharing one universal set of weights.

## Candidate union

- weighted Reciprocal Rank Fusion;
- configurable `rrf_k` default around 60;
- 1-based rank convention;
- deduplicate by book ID;
- preserve per-source raw score/rank/RRF contribution.

## V1 ranker

Create ranker interface and deterministic implementation.

Use interpretable features such as:

- fusion score;
- number of independent agreeing sources;
- generator-specific relevance;
- content/collaborative relevance;
- popularity/quality prior;
- recency/evidence strength;
- negative semantic evidence;
- surface coherence.

Do not train an engagement model yet.

## Reranker

Implement deterministic greedy/MMR-like surface policy.

- Home: strongest multi-interest coverage/diversity + small controlled exploration.
- Shelf: lighter diversity, target-shelf coherence dominates.
- Similar: very light diversity, source-book relevance dominates.

Track reranking diagnostics without bloating production persistence.

## Tests

- exact RRF math;
- multi-source candidate retains all provenance;
- surface weights differ;
- Home covers multiple interests when available;
- same-author/semantic repetition control behaves as configured;
- Similar is not over-personalized;
- deterministic final order.

---

# Phase 8 — Pipeline engine integration, cold-start UI and serving switch

## Goal

Integrate the completed funnel into the application and make it the normal path.

## Engine/wiring

- Implement/replace `FuturePipelineRecommendationEngine` using the pipeline components.
- Construct artifact-backed dependencies once per provider/process.
- Preserve `InProcessProvider`, timeout behavior, fallback provider, persisted batches and app-owned eligibility.
- Ensure no DB transaction remains open during inference.
- Ensure final engine order is authoritative.
- Validate all candidate book IDs against live catalog as existing service already does.
- Preserve/make truthful reason codes and reason text.
- Persist useful candidate provenance/diagnostics within existing result model limits.
- Set provider configuration to the real pipeline only after all required artifacts and tests are ready; retain easy fallback to popularity/mock for development as appropriate.

## Cold-start frontend

- Add skippable onboarding/taste-selection UX consistent with existing visual design.
- Reuse existing book search/card components where sensible.
- Do not force ratings or shelves.
- Support selection/deselection and completion/skip.
- Ensure keyboard accessibility/loading/error/empty states.
- A seeded new user should receive personalized Home candidates immediately after onboarding.

## Attribution frontend completion

- Verify all recommendation card actions, modal detail actions, and full detail-page actions preserve attribution where known.
- Do not carry stale attribution to unrelated navigation/actions.

## End-to-end tests

- seeded new user;
- skipped onboarding user;
- known user with multiple shelves/interests;
- Shelf surface reacts to target shelf;
- Similar reacts to source book and source graph;
- pagination persists same batch;
- provider failure degrades to popularity;
- no recommendation endpoint returns duplicates or prohibited exclusions.

---

# Phase 9 — Evaluation, performance hardening, diagnostics and documentation

## Goal

Prove the integrated system is understandable, reproducible and fast enough.

## Evaluation tooling

Add/finish commands such as:

```text
make build-recommender-artifacts
make evaluate-recommender
make inspect-recommender-profile USERNAME=<name>
```

Exact names should match repository conventions.

Provide evaluation/diagnostic reports for:

- ALS/item-item offline metrics;
- candidate-source coverage;
- final-result diversity/coverage by surface;
- cold-start behavior;
- qualitative semantic neighbours;
- inferred-interest inspection;
- fallback frequency under simulated missing artifacts.

## Performance

Profile fresh-batch inference on realistic contexts.

Track at least:

- context construction time;
- generator times;
- fusion/rank/rerank times;
- total provider time;
- artifact load time/memory;
- final batch fill rate.

Keep normal inference comfortably inside the existing timeout. Batch semantic matrix operations; avoid Python loops over the full catalog.

If performance is already acceptable, do not add ANN/vector infrastructure.

## Hardening

- verify deterministic behavior;
- verify artifact/catalog mismatch handling;
- verify first-request artifact load behavior;
- verify multi-worker memory implications are documented;
- verify recommendation persistence growth/cleanup policy is documented;
- confirm no new secret/PII logging;
- inspect all new migrations and downgrade paths.

## Docs

- final architecture diagram;
- artifact build instructions;
- model/config defaults;
- signal semantics;
- how live ALS fold-in works;
- how semantic interest clusters work;
- how to inspect user interests;
- surface configuration explanation;
- how to rebuild/tune models;
- known limitations and future session/learned-ranking path.

## Final acceptance

Run all repository quality commands, including e2e if environment permits. Record any environmental blockers explicitly.

---

# Fresh-session resume prompt

When starting a new Claude Code session after a context limit, use:

```text
Continue the Bookshelf recommender implementation from the repository's current state.

Read CLAUDE.md, RECOMMENDER_SPECIFICATION.md, RECOMMENDER_IMPLEMENTATION_PLAN.md, the relevant ADRs, and docs/implementation/plan.md. Inspect git status and preserve existing user changes.

Determine the first incomplete recommender phase from docs/implementation/plan.md. Work on that phase only. Verify the current code instead of assuming the original report is still exact. Run the required tests/checks for the phase, update docs/implementation/plan.md, and stop at a clean phase boundary with a concise summary of changes, commands run, failures/blockers, and the next phase.
```
