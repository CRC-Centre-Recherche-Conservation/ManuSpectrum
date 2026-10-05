# Operator commands of the ManuSpectrum stack:  make -C deploy <target>
# No target removes a volume: data volumes are external, so even a Compose
# command that asks for volumes to be removed leaves them; deleting one is a
# manual, documented gesture.
COMPOSE_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))/compose
ENV_FILE ?= $(COMPOSE_DIR)/.env
COMPOSE := docker compose --project-directory $(COMPOSE_DIR) --env-file $(ENV_FILE) \
	-f $(COMPOSE_DIR)/compose.yaml -f $(COMPOSE_DIR)/compose.prod.yaml
SECRETS_DIR ?= $(COMPOSE_DIR)/secrets
IMAGE ?= manuspectrum:local
EXTERNAL_VOLUMES := ms_pg_data ms_es_data ms_redis_broker ms_cantaloupe_cache

.PHONY: help config volumes secrets build init admin-password manage up down restart status logs smoke

help: ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(firstword $(MAKEFILE_LIST)) | sed 's/:.*## /\t/'

config: ## Validate the merged Compose files
	$(COMPOSE) config --quiet && echo "compose files valid"

volumes: ## Create the external data volumes (once per host, idempotent)
	@for v in $(EXTERNAL_VOLUMES); do \
		if docker volume inspect $$v >/dev/null 2>&1; then echo "$$v exists"; \
		else docker volume create $$v; fi; \
	done

# Each file is written to a temporary name and moved into place, so a failed
# generator leaves no empty secret; an existing file is never replaced.
SECRET_FILES := pg_password elastic_password django_secret_key email_password admin_password

secrets: ## Create the secrets directory (0700) and the secret files that are missing
	@command -v openssl >/dev/null || { echo "openssl is required to generate the secrets" >&2; exit 1; }
	@command -v python3 >/dev/null || { echo "python3 is required to generate the secrets" >&2; exit 1; }
	@install -d -m 0700 $(SECRETS_DIR)
	@cd $(SECRETS_DIR) && umask 077 && set -e && \
	for f in $(SECRET_FILES); do \
		[ -e $$f ] && continue; \
		case $$f in \
			pg_password|elastic_password|admin_password) openssl rand -base64 48 | tr -d '\n' > $$f.tmp ;; \
			django_secret_key) python3 -c "import secrets; print(secrets.token_urlsafe(64), end='')" > $$f.tmp ;; \
			email_password) : > $$f.tmp ;; \
		esac; \
		if [ "$$f" != email_password ] && [ ! -s $$f.tmp ]; then rm -f $$f.tmp; echo "could not generate $$f" >&2; exit 1; fi; \
		chmod 0444 $$f.tmp && mv -n $$f.tmp $$f; \
	done && ls -l $(SECRETS_DIR)

build: ## Build the image (CI or rehearsal VM, 10 GB free RAM; never the development VM)
	docker build -f $(COMPOSE_DIR)/../docker/Dockerfile -t $(IMAGE) $(COMPOSE_DIR)/../..

init: ## First installation only: Arches setup_db, refused when the database exists
	$(COMPOSE) up -d --wait postgres elasticsearch redis-broker redis-cache
	$(COMPOSE) run --rm -T web init

admin-password: ## Set the admin password from the admin_password secret (first install, rotation)
	$(COMPOSE) run --rm --no-deps -T web manage set_admin_password

manage: ## Run a management command, interactive: make -C deploy manage ARGS="changepassword admin"
	$(COMPOSE) run --rm --no-deps web manage $(ARGS)

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
