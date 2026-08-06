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
    PATH="/workspace/.venv/bin:${PATH}"

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=10s \
    CMD python3 -c "import urllib.request as u; u.urlopen('http://localhost:8000/api/v1/health/live', timeout=3)"


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
COPY pyproject.toml uv.lock* ./
COPY apps/api ./apps/api
COPY packages/recommender ./packages/recommender
RUN uv sync --package book-app --no-dev

# Runs as a non-root user (spec §14's security posture extended to the
# container itself, not just the application) — a fixed uid (not the
# default sequential one useradd would pick) so it matches predictably
# across rebuilds, e.g. for volume ownership if one is ever added.
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /workspace
USER appuser

# No --reload, and explicitly not `uv run` (which would want dev-group
# resolution available) — invoke the installed venv's uvicorn directly.
CMD [".venv/bin/uvicorn", "book_app.main:app", "--host", "0.0.0.0", "--port", "8000"]
