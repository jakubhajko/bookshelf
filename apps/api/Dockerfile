# syntax=docker/dockerfile:1
#
# Multi-stage: `dev` (docker-compose.yml's target — bind-mounted, hot
# reload, full workspace incl. dev tooling) and `production` (Phase 9,
# spec §18 — hardened: no reload, no dev dependencies, non-root user, only
# the two packages actually needed at runtime). Neither stage has been
# runtime-verified in this environment — Docker is not installed (see
# docs/implementation/plan.md §6 risks, unchanged since Phase 1) — `dev`
# was already exercised indirectly (the app it builds is what every phase
# has run natively against the project-local Postgres cluster instead);
# `production` is new this phase and validated only by config review and
# `docker compose config`-equivalent YAML parsing, not a real build.
#
# Build context is the repo root (see ../../.dockerignore).
#
#   docker build --target dev -f apps/api/Dockerfile .          (local, via docker-compose.yml)
#   docker build --target production -f apps/api/Dockerfile .   (spec §17's ECR/ECS image)

FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.10.4 /uv /uvx /usr/local/bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
ENV PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/workspace/.venv \
    PATH="/workspace/.venv/bin:${PATH}" \
    PORT=8000

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=10s \
    CMD python3 -c "import os, urllib.request as u; u.urlopen('http://localhost:%s/api/v1/health/live' % os.environ.get('PORT', '8000'), timeout=3)"


# --- dev: unchanged from Phase 1 --------------------------------------------
FROM base AS dev

COPY pyproject.toml uv.lock* ./
COPY apps/api ./apps/api
COPY packages/recommender ./packages/recommender
RUN uv sync --all-packages

CMD ["uv", "run", "--project", "apps/api", "uvicorn", "book_app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]


# --- production: hardened, Phase 9 ------------------------------------------
FROM base AS production

# `--package book-app` (not `--all-packages`) resolves only apps/api's own
# dependency closure — which already includes packages/recommender
# transitively via `[tool.uv.sources] book-recommender-engine = {workspace
# = true}` in apps/api/pyproject.toml — instead of every workspace member.
# `--no-dev` excludes both packages' `[dependency-groups] dev` (ruff/mypy/
# pytest/httpx2/pandas-stubs) — never needed at runtime, and ruff/mypy
# especially have no business being in a production image at all.
# Runs as a non-root user (spec §14's security posture extended to the
# container itself, not just the application) — a fixed uid (not the
# default sequential one useradd would pick) so it matches predictably
# across rebuilds, e.g. for volume ownership if one is ever added.
#
# The user is created and switched to BEFORE anything is copied or installed,
# and `chown` touches only the (still empty) /workspace directory itself, not
# its future contents. A trailing `chown -R appuser /workspace` would instead
# rewrite ownership on every file of the installed venv — and because Docker
# layers are copy-on-write and ownership is file metadata, that duplicated the
# entire ~338 MB venv into a second layer, making the production image LARGER
# than the dev one. `COPY --chown` + installing as appuser gets the same
# result in one layer.
RUN useradd --create-home --uid 1000 appuser && chown appuser:appuser /workspace
USER appuser

COPY --chown=appuser:appuser pyproject.toml uv.lock* ./
COPY --chown=appuser:appuser apps/api ./apps/api
COPY --chown=appuser:appuser packages/recommender ./packages/recommender
RUN uv sync --package book-app --no-dev

# Model artifacts ship *inside* the image (~244 MB), rather than being fetched
# from object storage when a container starts.
#
# The R2 sync in shared/storage/s3_artifacts.py still exists and still works —
# it is how artifacts reach a machine that has none, and it stays the path for
# any deployment that would rather not carry them in the image. It is simply
# not what production uses, because it was measured and it is too slow:
# downloading 244 MB from R2 on every cold start took 82-203 s (seven samples),
# at roughly 1.5-3 MB/s, and neither parallelising the transfers nor doubling
# the vCPU changed that. Cloud Run pulling the same bytes from Artifact
# Registry travels Google's own network instead of the public internet.
#
# The cost is that artifacts are now versioned *with* the code: changing a
# model means rebuilding and redeploying the image. For a recommender whose
# artifacts must already agree with the catalog they were trained against
# (ADR-0014, ADR-0020), coupling them to a deploy is arguably more correct
# than letting them drift independently.
#
# Requires data/artifacts/ to exist in the build context — `make
# build-recommender-artifacts`, or a download from R2. A missing directory
# fails the build loudly rather than producing an image that degrades at
# runtime.
COPY --chown=appuser:appuser data/artifacts ./data/artifacts

# No --reload, and explicitly not `uv run` (which would want dev-group
# resolution available) — invoke the installed venv's uvicorn directly.
# Cloud Run injects $PORT (usually 8080) and requires the server to listen on
# it; locally PORT defaults to 8000 (set in `base`), so nothing changes here.
# `sh -c exec` rather than plain shell form: `exec` replaces the shell process
# with uvicorn, so uvicorn stays PID 1 and actually receives the SIGTERM
# Cloud Run sends before shutting an instance down. Without `exec`, the shell
# is PID 1, swallows the signal, and every deploy ends in a 10s SIGKILL.
CMD ["sh", "-c", "exec .venv/bin/uvicorn book_app.main:app --host 0.0.0.0 --port ${PORT}"]
