# ADR-0013: The modular recommendation funnel is in scope

## Status

Accepted (Recommender Phase 0). Supersedes the *scope limitation* recorded in
ADR-0006, and only that — ADR-0006's provider/engine boundary decision
remains fully in force and is the seam this work plugs into.

## Context

ADR-0006 recorded, as an accepted decision, that building the real
recommendation funnel was "explicitly out of scope," and
`docs/implementation/plan.md` §7 closed with "Next phase: **None** — the
application is functionally complete." Both were correct under the
application specification that governed Phases 0-9, which deliberately
capped the recommender at mock/popularity engines behind a typed boundary.

That is no longer true. Root `CLAUDE.md` and `RECOMMENDER_SPECIFICATION.md`
now put the full funnel in scope, sequenced by
`RECOMMENDER_IMPLEMENTATION_PLAN.md`. Leaving ADR-0006's scope sentence and
the plan's "no next phase" statement standing would mean an active,
accepted instruction in the repository contradicts the specification that
now governs it — exactly the kind of silent divergence CLAUDE.md forbids.

The seam ADR-0006 built was verified against the live code during Phase 0
and is intact: `FuturePipelineRecommendationEngine` raises clearly rather
than fabricating data, `InProcessProvider`/`FallbackProvider` implement
spec §10.10's chain, `modules/recommendations/service.py` ends its read
transaction before calling the provider, and `ArtifactManifest` already
carries the `book_id`/`work_id`/`model_item_index` triple. Nothing about
the boundary needs to change to accommodate the funnel; that was its
purpose.

## Decision

The target funnel — surface configuration → five candidate-generator
families (ALS CF, item-item CF, semantic/content retrieval, resolved
source-similarity graph, popularity) → weighted rank fusion → deterministic
ranking → surface-specific reranking → authoritative persisted batch — is
in scope and will be implemented behind the existing boundary, one plan
phase at a time.

`FuturePipelineRecommendationEngine` is the plug point. Home, Shelf and
Similar Books share one pipeline implementation and differ only by typed
per-surface configuration (ADR-0017).

Everything ADR-0006 established is preserved unchanged:

- `packages/recommender` has zero FastAPI/SQLAlchemy imports;
- the application owns eligibility/exclusion rules and passes them in as
  hard exclusions;
- the API re-validates every returned candidate against the live catalog
  regardless of what the engine promised;
- engine output order is authoritative and nothing downstream re-sorts it;
- persisted batches and opaque cursors (ADR-0007) continue to serve
  pagination without re-running inference.

Popularity remains a real serving path, not a decommissioned one: it is
simultaneously a candidate source, the cold-start source, and the terminal
fallback.

## Alternatives considered

- **Amend ADR-0006 in place** — rejected. ADRs are a historical record of
  what was decided and why at a point in time; editing the decision out
  would erase the fact that the boundary was deliberately built *before*
  the funnel existed, which is the strongest evidence that the seam is real
  rather than retrofitted. ADR-0006 instead gets a status pointer here.
- **Replace the provider/engine boundary with direct pipeline calls from
  the service** — rejected. The boundary is what makes the funnel testable
  in isolation, keeps ORM concerns out of the recommender package, and
  preserves the fallback chain. Building the funnel is not a reason to
  discard the thing that was built to receive it.
- **Start the funnel without reconciling the contradicting documents
  first** — rejected. A future session resuming from
  `docs/implementation/plan.md` would have read "next phase: none" and
  ADR-0006's out-of-scope sentence as current instructions.

## Consequences

- `docs/implementation/plan.md` now tracks two completed phase sequences:
  the application plan (Phases 0-9, done) and the recommender plan
  (Phases 0-9, beginning here). Phase numbers are ambiguous unless
  qualified; the plan labels them explicitly.
- ADR-0006's "Alternatives considered" entry rejecting the funnel is now
  historical context, not a live constraint. Its Decision and Consequences
  sections remain live.
- The non-goals in `RECOMMENDER_SPECIFICATION.md` §29 (microservices,
  Redis/Celery/Kafka, vector databases, FAISS, learned neural rankers,
  learned sequence models, dwell/hover instrumentation) remain out of
  scope. "The funnel is in scope" does not reopen the infrastructure
  questions that earlier ADRs closed.
