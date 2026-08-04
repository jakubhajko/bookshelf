# ADR-0010: Dataset directory layout, git scope, and local Postgres for dev

## Status

Accepted. Unlike ADRs 0001–0009 (already approved in the specification), this
one records a Phase 0 decision for details the spec left unspecified, per
CLAUDE.md: "When a detail is genuinely missing, choose a conservative,
reversible default and document it."

## Context

Three concrete, unspecified details had to be resolved before Phase 1 could
safely begin:

1. The repo root contained ~10 GB of dataset files (raw Goodreads/Book-Crossing
   dumps, the canonical Parquet tables, 102,435 cover images, two notebooks,
   and a build cache) with no separation between "raw source," "canonical
   derived dataset," and "notebook scratch," and spec §4 defines a
   `data/{raw,processed,sample}` layout that didn't exist yet.
2. No git repository existed for this project, and the user's `$HOME`
   directory is itself an unrelated, empty, zero-commit git repository
   (confirmed: `git -C ~ rev-parse --show-toplevel` → `/Users/jakubhajko`,
   `git -C ~ log` → no commits). This is a pre-existing environment
   condition, not something this task introduced.
3. Docker is not installed in this environment, but Phase 1 needs to prove
   the API actually boots and can reach PostgreSQL, not just that files
   parse.

## Decision

1. **Data layout**: moved (same-volume rename, no copy) the existing files
   into `data/raw/{goodreads,book-crossing}/` (original third-party sources),
   `data/processed/` (`books.parquet`, `interactions.parquet`, `covers/`, and
   the not-directly-imported edition-level/manifest artifacts — see
   ADR-0005), `data/notebooks/` (the two build/inspection notebooks and their
   execution cache), and an empty `data/sample/` for a future
   sampling-code-generated test fixture. Documented in `data/README.md`.
2. **Git scope**: ran `git init` inside `/Users/jakubhajko/Projects/bookshelf`
   only, creating a nested repository exactly like this user's other local
   projects already do (confirmed: `BubbLive`, `rack`, `word2vec-numpy`,
   `rag-hallucination-detection`, and `test` under `~/Projects/` each have
   their own `.git`). Git treats a nested `.git` as an independent repo
   boundary — commands run from inside `bookshelf/` never touch the outer
   repo. Nothing in `$HOME` or its `.gitignore` was modified. `.gitignore`
   was written *before* the first `git add`, explicitly excluding
   `data/raw/`, `data/processed/`, and the notebook cache, with `data/sample/`
   and `data/README.md` explicitly un-ignored — verified by staging and
   confirming only 9 small files (no dataset files) were added.
3. **Local Postgres for dev/validation**: a project-local PostgreSQL 17
   cluster at `.pgdata/` (gitignored), a non-default port (5434, chosen to
   avoid colliding with both the Postgres default 5432 and this user's other
   project on 5433), started/stopped via `make db-start`/`make db-stop`
   rather than a Homebrew background service — the same operational pattern
   already used in this user's other local-Postgres project. This lets
   `/api/v1/health/ready` be validated against a real PostgreSQL instance
   without Docker.

## Alternatives considered

- **Leave dataset files at the repo root** — rejected; spec §4 defines a
  `data/` layout explicitly, and leaving multi-gigabyte files at the root
  makes `.gitignore` correctness harder to verify by inspection and mixes
  "source of truth for the app" with "build scratch" in one directory.
- **Copy instead of move the dataset files** — rejected; would double ~10 GB
  of disk usage for no benefit, since the originals aren't referenced from
  anywhere else on this machine that this task is aware of, and the move is
  a same-volume rename (instant, not a real copy).
- **Fix the outer `$HOME` repo (add a `Projects/` ignore rule, etc.)** —
  rejected as out of scope. It's a pre-existing condition affecting multiple
  unrelated projects, already handled the same way (nested repos) across
  this user's other work; changing shared home-directory configuration isn't
  this project's call to make unasked.
- **Skip local Postgres validation and only hand-inspect the Docker Compose
  YAML** — rejected; would let a real runtime bug (bad connection string,
  missing dependency, broken health-check logic) through Phase 1 unnoticed.
  Native validation is strictly more thorough than YAML parsing alone.

## Consequences

- Any future contributor/script that assumed dataset files live at the repo
  root needs to use the new `data/{raw,processed,notebooks,sample}` paths;
  there are none yet (Phase 2 is the first code that reads them), so this
  has no migration cost today.
- The project-local Postgres cluster is a second way to run Postgres locally
  (alongside the Compose `db` service, once Docker is available) — both must
  keep working, since Docker's absence here is specific to this environment,
  not a permanent project constraint. `make db-start`/`db-stop` and the
  Compose `db` service are documented as alternatives in `README.md`, not as
  a replacement for each other.
- Because `data/raw/` and `data/processed/` are gitignored, cloning this repo
  fresh will not include the dataset — `data/README.md` and (once Phase 2
  lands) the import command's error messages are the only guide to
  regenerating or fetching it. This is intentional (spec never asks for the
  dataset to be versioned in git) but worth stating so it isn't mistaken for
  data loss.
