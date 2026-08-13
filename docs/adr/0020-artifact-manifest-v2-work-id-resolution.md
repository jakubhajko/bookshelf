# ADR-0020: Artifact manifest schema 2 — compact item mapping, resolved by `work_id` at load

## Status

Accepted (Recommender Phase R3). Implements and narrows ADR-0014; supersedes
no decision, but changes the on-disk artifact format ADR-0014 assumed.

## Context

ADR-0014 fixed the runtime boundary (artifacts, not database reads) and named
the `book_id`/`work_id`/`model_item_index` triple as the stable item mapping.
It did not fix how that mapping is *stored* or how it is *used at load time*.
Recommender Phase R0 flagged both as open (drift-ledger items 10 and 15), and
R3 is the phase that has to answer them, because it is the first with more
than one artifact family.

Two measurements against the real 92,524-book catalog decided it.

**The manifest was the wrong container for the mapping.** Schema version 1
inlined one Pydantic object per catalog item, giving an 8.9 MB `manifest.json`
that took 0.22 s to parse into ~55 MB of resident objects — per family, per
worker process. The same object graph was also written into the
`model_versions.manifest` JSONB column, at 1.56 MB per row after compression.
Five families would have meant roughly a second of startup and a quarter of a
gigabyte of Python objects before serving a request, to hold data that is two
integer columns and a string column.

**The stored `book_id` cannot be trusted, and the code was trusting it.** The
v1 loader read `manifest.item_mapping[i].book_id` and served it directly.
That is correct exactly as long as the catalog has not been re-imported since
the build. After a re-import, PostgreSQL's autoincrement hands the same
integers to different books, and the artifact serves confidently wrong
results — the failure ADR-0014 describes as "invisible, produces
plausible-looking output, and corrupts every downstream metric". ADR-0014
already says `work_id` is the durable identity; what was missing was the step
that *uses* it.

## Decision

**Manifest schema version 2.** The manifest holds metadata only: model name
and version, catalog version, `trained_at`, item count, `preprocessing_version`,
optional `training_transform_version`, the serializable build `config`
(rec-spec §26), and a `files` list carrying each payload's SHA-256 and size.
A version 1 manifest fails validation, which surfaces as the ordinary
"artifact unreadable → degrade to fallback" path and prompts a rebuild.
Artifacts are regeneratable by design, so this is not a migration.

**The item mapping is a compact `mapping.npz`** beside the manifest: an
`int64` `book_ids` column and a `work_ids` string column, where
`model_item_index` is the array position. Strings are stored as a UTF-8 blob
plus offsets rather than a fixed-width NumPy unicode dtype, which would pad
every entry to the longest.

**Resolution happens through `work_id` at load time.** Every family loader
looks each `work_id` up in a `CatalogSnapshot` the application reads once at
provider construction, and serves the `book_id` that is correct *now*. The
`book_id` recorded at build time is kept only as a drift diagnostic
(`reassigned_count`). Outcomes are three:

- **OK** — everything resolved.
- **DEGRADED** — some items are gone from the catalog; they are dropped and
  counted, and the artifact is served without them.
- **REJECTED** — more than 10% unresolved. The artifact is not served; the
  caller degrades to the popularity floor.

**Payload files are deterministic and checksummed.** `save_arrays` writes the
`.npz` container itself with fixed zip timestamps and sorted members, so two
builds from the same input produce byte-identical payloads and "deterministic
artifact build" (rec-spec §28) is a testable claim rather than an intention.
Checksums are verified at load (3 ms for a 2.6 MB artifact), which catches the
one corruption a manifest cannot describe: a half-written or partially-copied
directory.

**No pickle, ever.** `allow_pickle=False` on every read and write, and bundle
members that are not genuine NumPy arrays are rejected rather than passed
through as raw bytes. An artifact directory must not be a code-execution
vector pointed at whatever wrote it.

## Alternatives considered

- **Keep the mapping in the manifest, accept the cost** — rejected on the
  measurement above. It is the only part of the manifest that scales with the
  catalog, and it is the part least suited to JSON.
- **Serve the artifact's stored `book_id` and reject on any catalog-version
  mismatch** — rejected. The version string changes when *any* book's
  `updated_at` moves, so this would reject artifacts that are perfectly
  serviceable, while still being wrong in the one case it was meant to catch
  if a rebuild happened to produce a matching string. Re-resolving is both
  safer and more permissive.
- **Reject when book ids have been reassigned** — rejected. Reassignment is
  the *normal* consequence of a re-import and resolution already handles it
  correctly; treating it as an error would make routine reimports break
  serving. It is logged instead.
- **Share one `mapping.npz` across all families** — rejected. Families order
  their items differently (popularity's order *is* its ranking), so a shared
  mapping would force an indirection on every family to save ~500 KB.
- **Delete unrecognized files when rebuilding an artifact directory** —
  rejected. The loader reads only what the manifest declares, so a leftover
  file is inert; a builder that deletes unknown files in a directory it was
  merely pointed at is a worse failure mode than a stale one. The build
  reports them instead.

## Consequences

- Loading all three families against the real catalog costs ~1.8 s and 77 MB
  per worker, against a v1 projection of ~1.1 s and ~275 MB for the mappings
  alone. `model_versions.manifest` rows dropped from 1.56 MB to ~750 bytes.
- Most of the remaining 77 MB is the item-metadata table's Python string
  tuples, not the numeric columns. If per-worker memory becomes the binding
  constraint, decoding titles/authors lazily is the lever — a Phase R9
  profiling question, deliberately not pre-optimized here.
- A re-import no longer requires an artifact rebuild for *correctness*, only
  for freshness. Books added since the build are simply absent from
  candidates, and books removed are dropped with a logged count.
- The 10% rejection threshold is a judgement, not a measurement. It is a
  named constant with the reasoning attached, and is the first thing to
  revisit if a legitimate operational state ever trips it.
