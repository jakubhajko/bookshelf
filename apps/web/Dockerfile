# syntax=docker/dockerfile:1
#
# Multi-stage: `dev` (docker-compose.yml's target — Vite dev server, hot
# reload via a bind mount) and `production` (Phase 9, spec §17 — the
# static `npm run build` output served by nginx, standing in locally for
# what S3+CloudFront serves on AWS). Neither runtime-verified in this
# environment — Docker is not installed (see docs/implementation/plan.md
# §6 risks, unchanged since Phase 1).
#
# Build context is ./apps/web (docker-compose.yml), not the repo root —
# unlike apps/api/Dockerfile — so nginx.conf.template lives alongside this
# file instead of under the repo's shared infra/docker/.
#
#   docker build --target dev -f apps/web/Dockerfile apps/web           (local, via docker-compose.yml)
#   docker build --target production -f apps/web/Dockerfile apps/web \
#     --build-arg VITE_API_BASE_URL=https://api.example.com

FROM node:22-slim AS dev
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]


# --- build: compiles the static bundle, not shipped itself ------------------
FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Vite env vars are compile-time, baked into the JS bundle here — not
# readable/overridable at container-start the way a backend env var is.
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build


# --- production: static files served by nginx -------------------------------
FROM nginx:1.27-alpine AS production
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
# Matches VITE_API_BASE_URL above in a real build — see
# nginx.conf.template's own comment for why it's supplied twice.
ENV API_ORIGIN=http://localhost:8000

EXPOSE 80
HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=5s \
    CMD wget -q -O /dev/null http://localhost:80/ || exit 1
