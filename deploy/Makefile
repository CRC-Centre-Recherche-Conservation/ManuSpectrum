# Operator commands of the ManuSpectrum stack:  make -C deploy <target>
# No target removes a volume: data volumes are external, so even a Compose
# command that asks for volumes to be removed leaves them; deleting one is a
# manual, documented gesture.
COMPOSE_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))/compose
ENV_FILE ?= $(COMPOSE_DIR)/.env
COMPOSE := docker compose --project-directory $(COMPOSE_DIR) --env-file $(ENV_FILE) \
	-f $(COMPOSE_DIR)/compose.yaml -f $(COMPOSE_DIR)/compose.prod.yaml
IMAGE ?= manuspectrum:local
EXTERNAL_VOLUMES := ms_pg_data ms_es_data ms_redis_broker ms_cantaloupe_cache

.PHONY: help config volumes build init up down restart status logs smoke

help: ## List the targets
	@grep -E '^[a-z]+:.*## ' $(firstword $(MAKEFILE_LIST)) | sed 's/:.*## /\t/'

config: ## Validate the merged Compose files
	$(COMPOSE) config --quiet && echo "compose files valid"

volumes: ## Create the external data volumes (once per host, idempotent)
	@for v in $(EXTERNAL_VOLUMES); do \
		if docker volume inspect $$v >/dev/null 2>&1; then echo "$$v exists"; \
		else docker volume create $$v; fi; \
	done

build: ## Build the image (CI or rehearsal VM, 10 GB free RAM; never the development VM)
	docker build -f $(COMPOSE_DIR)/../docker/Dockerfile -t $(IMAGE) $(COMPOSE_DIR)/../..

init: ## First installation only: Arches setup_db, refused when the database exists
	$(COMPOSE) up -d --wait postgres elasticsearch redis-broker redis-cache
	$(COMPOSE) run --rm -T web init

# `up --wait` refuses a service whose healthcheck is disabled, and beat has
# none on purpose: wait for every other service, then start beat (it depends
# on a healthy web).
up: ## Start or update the stack and wait until it is healthy
	$(COMPOSE) up -d --wait --wait-timeout 900 $$($(COMPOSE) config --services | grep -vx beat)
	$(COMPOSE) up -d beat

down: ## Stop and remove the containers; volumes are kept
	$(COMPOSE) down

restart: ## Restart the application containers
	$(COMPOSE) restart web worker beat

status: ## Containers and their health
	$(COMPOSE) ps

logs: ## Follow the last 200 lines of every service
	$(COMPOSE) logs --tail=200 -f

smoke: ## Read-only checks of the running stack
	$(COMPOSE_DIR)/smoke.sh check
