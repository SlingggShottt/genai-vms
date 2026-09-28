.DEFAULT_GOAL := help

COMPOSE_FILE := deploy/compose/docker-compose.yml
PROFILE ?=
SVC ?=

.PHONY: help setup up down test test-int lint topics sim

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Install Python + Node dependencies and pre-commit hooks
	uv sync --all-packages
	@if [ -f frontend/package.json ]; then cd frontend && npm ci; else \
		echo "frontend/ not scaffolded yet (lands in P1-J4) — skipping npm ci"; fi
	uv run pre-commit install

up: ## Start docker compose profiles, e.g. make up PROFILE=infra,core
	@if [ -z "$(PROFILE)" ]; then echo "usage: make up PROFILE=infra[,core,perception,genai,tools,obs,lite]"; exit 1; fi
	@if [ ! -f $(COMPOSE_FILE) ]; then echo "$(COMPOSE_FILE) not created yet (lands in P1-D3)"; exit 1; fi
	COMPOSE_PROFILES=$(PROFILE) docker compose -f $(COMPOSE_FILE) up -d

down: ## Stop and remove docker compose services
	@if [ ! -f $(COMPOSE_FILE) ]; then echo "$(COMPOSE_FILE) not created yet (lands in P1-D3)"; exit 1; fi
	docker compose -f $(COMPOSE_FILE) down

topics: ## Create Kafka topics from design_architecture.md §5.2 (needs `make up PROFILE=infra` first)
	bash deploy/compose/scripts/create_topics.sh

sim: ## Replay dataset videos as live RTSP cameras (needs config/camera_sim.yaml, see tools/camera_sim/README.md)
	uv run --package vms-camera-sim camera-sim

test: ## Run Python unit tests; make test SVC=perception for one service
	@if [ -n "$(SVC)" ]; then \
		uv run pytest services/$(SVC) -m "not integration"; \
	else \
		uv run pytest -m "not integration"; \
	fi

test-int: ## Run integration tests (testcontainers: Kafka/Postgres/Qdrant)
	uv run pytest -m integration

lint: ## ruff check + ruff format --check (+ eslint once frontend exists)
	uv run ruff check .
	uv run ruff format --check .
	@if [ -f frontend/package.json ]; then cd frontend && npm run lint; fi
