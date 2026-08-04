.DEFAULT_GOAL := help

LOCAL_PGDATA := .pgdata
LOCAL_PGPORT := 5434
LOCAL_PGUSER := book_app
LOCAL_PGDB   := book_app
LOCAL_PGHOST := localhost

.PHONY: help setup dev dev-api dev-web up down logs \
        db-start db-stop db-shell \
        migrate import-data import-data-dry-run seed-demo build-popularity \
        test lint typecheck e2e generate-api-client

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

## --- Setup & local processes -----------------------------------------------

setup: ## Install backend (uv workspace) and frontend (npm) dependencies
	uv sync --all-packages
	cd apps/web && npm install

dev: ## Reminder: run the API and web dev servers (two terminals; no Docker required)
	@echo "Run 'make dev-api' and 'make dev-web' in separate terminals."
	@echo "(No process manager is wired yet - see docs/implementation/plan.md Phase 1 notes.)"

dev-api: ## Run the FastAPI app with reload against the local Postgres cluster
	cd apps/api && uv run uvicorn book_app.main:app --reload --port 8000

dev-web: ## Run the Vite dev server
	cd apps/web && npm run dev

## --- Docker Compose (requires Docker - see docs/implementation/plan.md risks) ---

up: ## docker compose up --build
	docker compose up --build

down: ## docker compose down
	docker compose down

logs: ## docker compose logs -f
	docker compose logs -f

## --- Project-local PostgreSQL (no Docker required) -------------------------

db-start: ## Start the project-local Postgres cluster, creating it on first run
	@if [ ! -d "$(LOCAL_PGDATA)" ]; then \
		initdb -D $(LOCAL_PGDATA) -U $(LOCAL_PGUSER) -E UTF8 --auth=trust --no-instructions; \
	fi
	@pg_ctl -D $(LOCAL_PGDATA) status >/dev/null 2>&1 || \
		pg_ctl -D $(LOCAL_PGDATA) -l $(LOCAL_PGDATA)/server.log -o "-p $(LOCAL_PGPORT) -k /tmp" start
	@psql -h $(LOCAL_PGHOST) -p $(LOCAL_PGPORT) -U $(LOCAL_PGUSER) -d postgres -tc \
		"SELECT 1 FROM pg_database WHERE datname = '$(LOCAL_PGDB)'" | grep -q 1 || \
		createdb -h $(LOCAL_PGHOST) -p $(LOCAL_PGPORT) -U $(LOCAL_PGUSER) $(LOCAL_PGDB)
	@psql -h $(LOCAL_PGHOST) -p $(LOCAL_PGPORT) -U $(LOCAL_PGUSER) -d $(LOCAL_PGDB) \
		-c "CREATE EXTENSION IF NOT EXISTS pg_trgm;" >/dev/null
	@echo "Postgres ready at postgresql://$(LOCAL_PGUSER)@$(LOCAL_PGHOST):$(LOCAL_PGPORT)/$(LOCAL_PGDB)"

db-stop: ## Stop the project-local Postgres cluster
	@pg_ctl -D $(LOCAL_PGDATA) status >/dev/null 2>&1 && \
		pg_ctl -D $(LOCAL_PGDATA) stop -m fast || echo "already stopped"

db-shell: ## Open a psql shell against the project-local cluster
	psql -h $(LOCAL_PGHOST) -p $(LOCAL_PGPORT) -U $(LOCAL_PGUSER) -d $(LOCAL_PGDB)

## --- Data / recommender pipeline (phase-gated, see plan.md) ----------------

migrate: ## Apply Alembic migrations
	cd apps/api && uv run alembic upgrade head

import-data: ## Import books.parquet (catalog + taxonomy) into PostgreSQL
	cd apps/api && uv run python -m book_app.cli.import_catalog

import-data-dry-run: ## Validate the dataset without writing to PostgreSQL
	cd apps/api && uv run python -m book_app.cli.import_catalog --dry-run

seed-demo: ## Create the local demo user with representative shelves/ratings/saves
	@echo "Not implemented yet - lands in Phase 4+ (see docs/implementation/plan.md)."

build-popularity: ## Build the popularity recommendation artifact
	@echo "Not implemented yet - lands in Phase 5 (see docs/implementation/plan.md)."

## --- Quality gates -----------------------------------------------------------

test: ## Run backend, recommender, and frontend test suites (fast, no live Postgres needed)
	cd apps/api && uv run pytest --cov=book_app --cov-report=term-missing
	cd packages/recommender && uv run pytest
	cd apps/web && npm run test

test-integration: ## Run tests/integration (spec §13.3) - requires Postgres (make db-start first)
	cd apps/api && uv run pytest ../../tests/integration -v

lint: ## Run backend and frontend linters
	cd apps/api && uv run ruff format --check . && uv run ruff check .
	cd packages/recommender && uv run ruff format --check . && uv run ruff check .
	uv run --project apps/api ruff format --check tests
	uv run --project apps/api ruff check tests
	cd apps/web && npm run lint

typecheck: ## Run backend and frontend type checkers
	cd apps/api && uv run mypy .
	cd packages/recommender && uv run mypy .
	cd apps/web && npm run typecheck

e2e: ## Run Playwright critical-flow tests
	@echo "Not implemented yet - lands in Phase 9 (see docs/implementation/plan.md)."

generate-api-client: ## Generate the frontend API client from the FastAPI OpenAPI schema
	@echo "Not implemented yet - lands in Phase 6 (see docs/implementation/plan.md)."
