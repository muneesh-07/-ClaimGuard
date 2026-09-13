COMPOSE := docker compose -f infra/docker-compose.yml
# The wrapper and its .mvn/ live in backend/, so run it from there.
MVN     := cd backend && ./mvnw

.DEFAULT_GOAL := help

.PHONY: help up down logs ps build test run clean gen-data load-bulk

help: ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk -F':.*?## ' '{printf "  \033[36m%-8s\033[0m %s\n", $$1, $$2}'

up: ## Start infrastructure (Postgres, later Kafka + Redis)
	$(COMPOSE) up -d
	$(COMPOSE) ps

down: ## Stop infrastructure, keep volumes
	$(COMPOSE) down

logs: ## Tail infrastructure logs
	$(COMPOSE) logs -f

ps: ## Show infrastructure status
	$(COMPOSE) ps

build: ## Compile and package the backend
	$(MVN) -B clean package

test: ## Run the backend test suite (needs a Docker daemon for Testcontainers)
	$(MVN) -B test

run: ## Start the backend on :8080
	$(MVN) spring-boot:run

clean: ## Remove build output
	$(MVN) -B clean

gen-data: ## Generate synthetic claims + ground truth into data/ (override with CLAIMS=/RINGS=)
	python3 tools/gen_rings.py --claims $(or $(CLAIMS),50000) --rings $(or $(RINGS),120)

load-bulk: ## Bulk-load data/claims.csv via COPY, then resolve entities (needs `make up run` first)
	tools/load_bulk.sh data/claims.csv
