-- Runs once via Postgres's /docker-entrypoint-initdb.d/ mechanism when the
-- `db` volume is first created (spec §8: "Enable pg_trgm; optionally enable
-- vector for later use"). The compose `db` image is pgvector/pgvector:pg17,
-- so CREATE EXTENSION vector is available whenever a later phase needs it —
-- not enabled by default yet, since nothing uses it (no unused abstractions).
CREATE EXTENSION IF NOT EXISTS pg_trgm;
