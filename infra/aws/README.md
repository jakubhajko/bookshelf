# AWS architecture (target design, not provisioned)

Per `APP_SPECIFICATION.md` §17 and ADR-0009: this documents where each piece
of the stack *would* run on AWS. Nothing here is provisioned in version one —
no Terraform/CDK, no live AWS resources. The point is that the application is
built so this mapping requires no architecture change when it happens, not
that it happens now.

| Component | Local (today) | AWS (future) |
|---|---|---|
| Frontend build | `apps/web` via Vite/Docker | S3 + CloudFront |
| API | `apps/api` via uvicorn/Docker | ECR image on ECS Fargate, behind an Application Load Balancer |
| Database | Project-local Postgres (`make db-start`) or the Compose `db` service | RDS for PostgreSQL (pgvector-compatible) |
| Cover images | `data/processed/covers/` (local storage backend) | S3 + CloudFront (S3 storage backend, same interface) |
| Model artifacts | `data/artifacts/` (local storage backend) | S3 (S3 storage backend, same interface) |
| Secrets | `.env` (gitignored, local only) | Secrets Manager or SSM Parameter Store |
| Logs | Structured JSON to stdout | CloudWatch Logs (no shipper needed — stdout JSON is ingestible directly) |
| Container images | Built locally | ECR |

## What makes this a lift, not a rewrite

- **Stateless API containers.** Nothing the API depends on across requests
  lives on local disk outside a configured storage root; horizontal scaling
  on Fargate doesn't change application behavior.
- **Environment-based configuration.** `apps/api/src/book_app/core/config.py`
  is the only place that reads configuration; swapping `.env` for
  Secrets Manager/SSM-injected environment variables requires no code change.
- **Explicit migrations.** Alembic migrations (Phase 2) run as a one-off
  deployment task against RDS, the same command used locally against the
  project-local/Compose Postgres — never implicitly on container startup.
- **Storage abstractions.** Covers and model artifacts are read through a
  backend interface with `local` and `s3` implementations (spec §7.3,
  §10.13); moving either to S3 is a config change
  (`COVER_STORAGE_BACKEND=s3`, `ARTIFACT_STORAGE_BACKEND=s3`), not a code
  change in the modules that use them.
- **Health checks.** `GET /api/v1/health/live` and `GET /api/v1/health/ready`
  (spec §9.7) are what an ALB target group or ECS task definition would
  point at.

See `docs/adr/0009-local-first-aws-ready-design.md` for the reasoning behind
deferring provisioning, and `docs/implementation/plan.md` for what's actually
built so far.
