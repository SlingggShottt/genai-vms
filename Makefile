.DEFAULT_GOAL := help

COMPOSE_FILE := deploy/compose/docker-compose.yml
# Compose reads `.env` from the directory of the compose file (deploy/compose/),
# not the repo root — so the root `.env` that .env.example tells you to create
# would be silently ignored ("required variable POSTGRES_PASSWORD is missing").
# Pass it explicitly.
ENV_FILE ?= .env
COMPOSE := docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE)
PROFILE ?=
SVC ?=

.PHONY: help setup up down test test-int lint topics qdrant-collections sim migrate migration k8s-render k8s-up k8s-down demo demo-stop

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
	@if [ ! -f $(ENV_FILE) ]; then echo "$(ENV_FILE) not found — run: cp .env.example .env, then fill in the secrets"; exit 1; fi
	COMPOSE_PROFILES=$(PROFILE) $(COMPOSE) up -d

down: ## Stop and remove docker compose services
	@if [ ! -f $(COMPOSE_FILE) ]; then echo "$(COMPOSE_FILE) not created yet (lands in P1-D3)"; exit 1; fi
	@if [ ! -f $(ENV_FILE) ]; then echo "$(ENV_FILE) not found — run: cp .env.example .env, then fill in the secrets"; exit 1; fi
	$(COMPOSE) down

migrate: ## Apply DB migrations (alembic upgrade head) — needs VMS_DB_DSN reachable
	uv run --package vms-db alembic -c libs/vms_db/alembic.ini upgrade head

migration: ## Create a new migration: make migration MSG="add zones"
	@if [ -z "$(MSG)" ]; then echo "usage: make migration MSG=\"description\""; exit 1; fi
	uv run --package vms-db alembic -c libs/vms_db/alembic.ini revision --autogenerate -m "$(MSG)"

topics: ## Create Kafka topics from design_architecture.md §5.2 (needs `make up PROFILE=infra` first)
	bash deploy/compose/scripts/create_topics.sh

qdrant-collections: ## Create Qdrant collections from design_architecture.md §6.2 (needs `make up PROFILE=infra` first)
	uv run --package vms-common python deploy/compose/scripts/create_qdrant_collections.py

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

# --- Kubernetes (minikube) and the host-side demo ---------------------------------------------
K8S_OVERLAY ?= deploy/k8s/overlays/minikube
KUBECTL ?= kubectl

k8s-render: ## Render the minikube manifests to stdout (needs overlays/minikube/secrets.env)
	@test -f $(K8S_OVERLAY)/secrets.env || { echo "copy $(K8S_OVERLAY)/secrets.env.example to secrets.env first"; exit 1; }
	$(KUBECTL) kustomize --load-restrictor=LoadRestrictionsNone $(K8S_OVERLAY)

k8s-up: ## Build the images into minikube and apply the manifests
	eval $$(minikube docker-env) && \
	  for s in api retrieval reasoning indexer events correlation ingestion perception; do \
	    docker build -t genai-vms-$$s:latest -f services/$$s/Dockerfile . || exit 1; done && \
	  docker build -t genai-vms-frontend:latest frontend
	$(MAKE) -s k8s-render | $(KUBECTL) apply -f -

k8s-down: ## Remove the minikube deployment (volumes included)
	$(MAKE) -s k8s-render | $(KUBECTL) delete --ignore-not-found -f -

demo: ## Start Ollama, retrieval, reasoning, api and the UI on the host (see deploy/demo/README.md)
	deploy/demo/start.sh

demo-stop: ## Stop what `make demo` started
	deploy/demo/stop.sh

demo-refresh: ## Re-record the demo footage on MEVA clips and run the rules + VLM gate (~45 min; DRY_RUN=1 to check first)
	deploy/demo/refresh.sh
