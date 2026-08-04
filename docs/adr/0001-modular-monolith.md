# ADR-0001: Modular monolith architecture

## Status

Accepted (approved in `APP_SPECIFICATION.md` §3.1, §20 before implementation started).

## Context

The application needs strong logical separation between authentication, the
catalog, user preference state, shelves, search, and recommendations, plus a
recommendation subsystem that will grow substantially in scope over time
(candidate generation, ranking, reranking). It must also be easy to run and
deploy for a single team in early stages, and later map cleanly onto AWS
(ECS Fargate, RDS, S3/CloudFront) without a rewrite.

## Decision

Build a single deployable FastAPI application (`apps/api`) organized into
strongly-bounded modules (`modules/auth`, `modules/books`, `modules/shelves`,
`modules/interactions`, `modules/search`, `modules/recommendations`), each
following the same internal layering (`api.py` → `service.py` →
`repository.py`/provider interfaces → infrastructure). The recommendation
engine lives in a separate, independently importable Python package
(`packages/recommender`) with no FastAPI or ORM dependency, consumed through a
typed protocol. This is a modular monolith, not a set of network services.

## Alternatives considered

- **Microservices from day one** — rejected. Adds network boundaries,
  distributed transactions, and deployment complexity the product doesn't
  need yet, and explicitly forbidden by spec §2/§20.
- **Unstructured single FastAPI app with no module boundaries** — rejected.
  Would make the eventual extraction of the recommender (or any module) into
  a separate service much harder, and violates the "recommender package must
  not import FastAPI or ORM models" constraint from the start.
- **Django-style monolith with an ORM-centric MVC structure** — rejected.
  Spec explicitly names FastAPI + SQLAlchemy + a service/repository split, not
  a generic CRUD framework structure.

## Consequences

- Module boundaries are enforced by convention and code review, not by
  process/network isolation — a developer *can* violate them (e.g., import a
  repository directly from a route). Mitigated by keeping each module's
  internal layering consistent and reviewing dependency direction
  (`routes -> services -> repositories/provider interfaces -> infrastructure`).
- The recommender package's independence from FastAPI/ORM is verified by a
  repository-hygiene test (checking its dependency manifest and import graph)
  rather than by physical process separation.
- If a module later needs to become an independent service, its `service.py`
  boundary is already the natural extraction seam.
