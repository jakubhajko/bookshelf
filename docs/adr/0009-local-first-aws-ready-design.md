# ADR-0009: Local-first, AWS-ready design

## Status

Accepted (approved in `APP_SPECIFICATION.md` §3.3, §17, §20 before implementation started).

## Context

The project must run entirely on a local machine (Docker Compose, no cloud
account required) during development, while remaining a straightforward
lift onto AWS later without an architecture rewrite. Provisioning real AWS
infrastructure now would add cost, credentials management, and deployment
complexity with no user-facing benefit at this stage.

## Decision

Design for AWS without provisioning AWS: stateless API containers holding no
local state that matters across restarts; all configuration via environment
variables (no hardcoded/machine-specific paths anywhere in application code);
explicit, versioned Alembic migrations instead of implicit schema sync;
`/health/live` and `/health/ready` endpoints suitable for ALB/ECS health
checks; structured stdout logs suitable for CloudWatch ingestion without a
special log shipper; storage abstracted behind interfaces (local filesystem
today, S3-backed implementation of the same interface later) for both cover
images and model artifacts; versioned, immutable model artifact manifests
(spec §10.13) so artifact storage can move to S3 without changing how the
provider loads them. The target mapping (web → S3/CloudFront, API → ECR/ECS
Fargate/ALB, DB → RDS, covers/artifacts → S3, secrets → Secrets
Manager/SSM, logs → CloudWatch) is documented but not built.

## Alternatives considered

- **Provision real AWS infrastructure now (Terraform/CDK, actual S3/RDS)** —
  explicitly rejected by spec §2/§17/§20 ("Do not provision production AWS
  infrastructure in version one"). Adds cost and operational surface before
  there's anything worth deploying.
- **Design only for local Docker Compose, defer AWS-readiness thinking
  entirely** — rejected; retrofitting statelessness, storage abstraction, or
  environment-based config after business logic hardcodes assumptions is far
  more expensive than deciding the seams now.
- **Migrations applied automatically on every container start** — rejected;
  spec §17 is explicit that migrations run "as a one-off deployment task, not
  destructively on every startup," which also matches the local Compose
  setup (migrations run via `make migrate`, not implicitly on `api` boot).

## Consequences

- Any code that would tie the app to "this machine" (absolute paths, local
  disk as a source of truth beyond a configured storage root, in-process
  state that must survive a restart) is a bug against this ADR, not a
  shortcut to revisit later.
- Local development without Docker is still fully supported (native
  PostgreSQL + `uv run`/`npm run dev`) because nothing in the design assumes
  containers specifically — only that configuration is environment-driven.
  This is what made Phase 1 verifiable in this environment despite Docker not
  being installed (see ADR-0010).
- The AWS mapping documented in `README.md`/spec §17 is a target, not a
  commitment to a timeline; nothing in the codebase should silently start
  depending on an AWS-only service (e.g. an AWS SDK call with no local
  fallack) before that phase is explicitly reached.
