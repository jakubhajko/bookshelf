# syntax=docker/dockerfile:1
#
# Development-oriented image (Vite dev server with hot reload via a bind
# mount in docker-compose.yml). A hardened production build (static export
# served via nginx locally / S3+CloudFront on AWS, spec §17) is a Phase 9
# task. Not runtime-verified in this environment — Docker is not installed
# (see docs/implementation/plan.md §6 risks).

FROM node:22-slim
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
