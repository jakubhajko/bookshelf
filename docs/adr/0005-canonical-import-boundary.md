# ADR-0005: Canonical import boundary over the Parquet dataset

## Status

Accepted (approved in `APP_SPECIFICATION.md` §7.4, §20 before implementation started).

## Context

The source dataset (`books.parquet`, `interactions.parquet`) has its own
column names, types, and quirks (e.g. `n_shelves` vs. `shelves`, rating 0
meaning "implicit, not negative," one row with an empty `work_id`). If
application code (services, routes, the recommender) reads Parquet columns
directly, every consumer has to know those quirks, and any future change to
the dataset build process becomes a multi-file refactor.

## Decision

A single dataset adapter (`scripts/data_import/` + the `import_catalog` CLI)
is the only code allowed to know raw Parquet column names. It produces
canonical, typed records that the rest of the application consumes. Import is
explicit (a CLI command, never run at API startup), idempotent (safe to
re-run), batched, validated (e.g. rejects the empty-`work_id` row rather than
silently upserting it), dry-run capable, and generates a report. Upserts are
keyed by `work_id`, independent of Parquet row order, and non-destructive by
default. `work_id -> books.id` is preserved explicitly everywhere it matters,
including future model artifacts (`book_id`, `work_id`, `model_item_index`
stored together, per spec §7.5).

## Alternatives considered

- **Import at API startup** — explicitly rejected by spec §7.4/§20. Would
  make container startup slow and non-deterministic, and couple app
  availability to a multi-GB batch job.
- **Let services query Parquet columns directly via a shared "dataset"
  helper** — rejected. Leaks raw column knowledge across every module instead
  of containing it, exactly the coupling spec §20 forbids ("Do not couple API
  code to raw Parquet fields outside the adapter").
- **Treat `books_editions.parquet` / `interactions_editions.parquet` as
  additional import sources** — rejected; per spec §2/§5.1 the app has no
  edition entity, and those files are already rolled up into the canonical
  work-level files (see `data/README.md`). Importing them separately would
  reintroduce an edition/work split the spec explicitly forbids.

## Consequences

- The adapter is the one place that changes if the dataset build process
  changes; every other module works with canonical typed records only.
- The importer must be re-run intentionally (`make import-data`,
  `make import-data-dry-run`), never as a side effect of deploying or
  starting the API — operational runbooks must say so explicitly.
- Data-quality issues discovered in the source (like the empty `work_id` row)
  are handled once, in the adapter's validation step, with a generated report
  — not discovered ad hoc later by a service crashing on bad data.
