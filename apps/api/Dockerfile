# syntax=docker/dockerfile:1
#
# Development-oriented image: docker-compose.yml bind-mounts apps/api and
# packages/recommender over what's copied here, for hot reload. Hardened,
# minimal multi-stage production builds are a Phase 9 task (spec §18) — not
# built prematurely here, and this image has not been runtime-verified in
# this environment (Docker is not installed — see docs/implementation/plan.md
# §6 risks). Build context is the repo root (see ../../.dockerignore).

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.10.4 /uv /uvx /usr/local/bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
ENV PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/workspace/.venv \
    PATH="/workspace/.venv/bin:${PATH}"

COPY pyproject.toml uv.lock* ./
COPY apps/api ./apps/api
COPY packages/recommender ./packages/recommender
RUN uv sync --all-packages

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=10s \
    CMD python3 -c "import urllib.request as u; u.urlopen('http://localhost:8000/api/v1/health/live', timeout=3)"

CMD ["uv", "run", "--project", "apps/api", "uvicorn", "book_app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
