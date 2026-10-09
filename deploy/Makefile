# Operator commands of the ManuSpectrum stack:  make -C deploy <target>
# No target removes a volume: data volumes are external, so even a Compose
# command that asks for volumes to be removed leaves them; deleting one is a
# manual, documented gesture.
COMPOSE_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))/compose
ENV_FILE ?= $(COMPOSE_DIR)/.env
COMPOSE := docker compose --project-directory $(COMPOSE_DIR) --env-file $(ENV_FILE) \
	-f $(COMPOSE_DIR)/compose.yaml -f $(COMPOSE_DIR)/compose.prod.yaml
# SECRETS_DIR: the command line or environment, else the env file (a relative
# value resolves against COMPOSE_DIR, as Compose does), else compose/secrets.
# The last SECRETS_DIR line of the env file must be a plain SECRETS_DIR=/path
# (no export, spaces, quotes or comment), which is what this file reads and
# Compose reads alike; the check also runs when the command line overrides it,
# since Compose reads the env file anyway.
ENV_SECRETS_PATTERN := ^[[:space:]]*(export[[:space:]]+)?SECRETS_DIR[[:space:]]*=
ENV_SECRETS_LINE := $(shell grep -E '$(ENV_SECRETS_PATTERN)' '$(ENV_FILE)' 2>/dev/null | tail -n 1)
ifneq ($(shell grep -E '$(ENV_SECRETS_PATTERN)' '$(ENV_FILE)' 2>/dev/null | tail -n 1 | grep -cvE '^SECRETS_DIR=[^[:space:]"'\''\#]+$$'),0)
$(error SECRETS_DIR in $(ENV_FILE) must be a plain SECRETS_DIR=/path line (no export, quotes, spaces or comment))
endif
ENV_SECRETS_DIR := $(patsubst SECRETS_DIR=%,%,$(ENV_SECRETS_LINE))
SECRETS_DIR ?= $(if $(ENV_SECRETS_DIR),$(if $(filter /%,$(ENV_SECRETS_DIR)),$(ENV_SECRETS_DIR),$(abspath $(COMPOSE_DIR)/$(ENV_SECRETS_DIR))),$(COMPOSE_DIR)/secrets)
SCRIPTS_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))/scripts
IMAGE ?= manuspectrum:local
EXTERNAL_VOLUMES := ms_pg_data ms_es_data ms_redis_broker ms_cantaloupe_cache ms_prometheus_data
# A value of the env file, read the way the file is written (KEY=value, no quoting).
envval = $$(sed -n 's/^$(1)=//p' $(ENV_FILE) | tail -n 1)

.PHONY: help config volumes secrets secret-set secrets-check secrets-dir build init admin-password manage load-snapshot backup-init backup restore-test restore restore-files restic up down restart status logs smoke nginx-test nginx-reload certs-local cert-init cert-renew observability-on observability-off monitoring-init container-metrics disk-usage alert-recipients alert-test alerts silence silence-fresh-install monthly-report report-test

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
SECRET_FILES := pg_password elastic_password django_secret_key email_password admin_password restic_password grafana_admin_password pg_monitor_password

secrets: ## Create the secrets directory (0700) and the secret files that are missing
	@command -v openssl >/dev/null || { echo "openssl is required to generate the secrets" >&2; exit 1; }
	@command -v python3 >/dev/null || { echo "python3 is required to generate the secrets" >&2; exit 1; }
	@install -d -m 0700 $(SECRETS_DIR)
	@cd $(SECRETS_DIR) && umask 077 && set -e && \
	for f in $(SECRET_FILES); do \
		[ -e $$f ] && continue; \
		case $$f in \
			pg_password|elastic_password|admin_password|restic_password|grafana_admin_password|pg_monitor_password) openssl rand -base64 48 | tr -d '\n' > $$f.tmp ;; \
			django_secret_key) python3 -c "import secrets; print(secrets.token_urlsafe(64), end='')" > $$f.tmp ;; \
			email_password) : > $$f.tmp ;; \
		esac; \
		if [ "$$f" != email_password ] && [ ! -s $$f.tmp ]; then rm -f $$f.tmp; echo "could not generate $$f" >&2; exit 1; fi; \
		chmod 0444 $$f.tmp && mv -n $$f.tmp $$f; \
	done && ls -l $(SECRETS_DIR)

secret-set: ## Set one secret from the terminal or stdin, never an argument: make -C deploy secret-set NAME=pg_password [FORCE=yes]
	@[ -n "$(NAME)" ] || { echo "set NAME=<one of: $(SECRET_FILES)>" >&2; exit 1; }
	@$(SCRIPTS_DIR)/secret-set.sh --dir '$(SECRETS_DIR)' --names '$(SECRET_FILES)' $(if $(filter yes,$(FORCE)),--force) '$(NAME)'

secrets-check: ## Check the secret files (presence, modes, lengths) without printing a value
	@$(SCRIPTS_DIR)/secrets-check.sh --dir '$(SECRETS_DIR)' --names '$(SECRET_FILES)'

secrets-dir: ## Print the secrets directory the make targets use
	@echo '$(SECRETS_DIR)'

build: ## Build the image (CI or rehearsal VM, 10 GB free RAM; never the development VM)
	docker build -f $(COMPOSE_DIR)/../docker/Dockerfile -t $(IMAGE) $(COMPOSE_DIR)/../..

# The package that init loads is the commit the application pins. After a
# `git pull` or `git checkout`, pkg/ keeps the old commit until
# `git submodule update --init`: `git submodule status` then starts with `-`
# (not initialised), `+` (another commit) or `U` (merge conflict), and init
# refuses. PKG_DIR (command line, environment or env file) is resolved to a real
# path and compared with the submodule's: any spelling of that path is checked,
# any other directory is used as given, with a notice. Without git, or outside
# a Git checkout (a release archive), init refuses while PKG_DIR is the
# submodule: set PKG_DIR to an extracted package to skip the check.
PKG_SUBMODULE := ../../pkg
REPO_ROOT := $(abspath $(COMPOSE_DIR)/../..)

init: ## First installation only: Arches setup_db, then the pkg submodule (PKG_DIR); refused when the database exists or pkg/ is not at the pinned commit
	@pkg_dir="$${PKG_DIR:-$$(sed -n 's/^PKG_DIR=//p' '$(ENV_FILE)' 2>/dev/null | tail -n 1)}"; \
	pkg_dir="$${pkg_dir:-$(PKG_SUBMODULE)}"; \
	case "$$pkg_dir" in /*) ;; *) pkg_dir='$(COMPOSE_DIR)'/"$$pkg_dir" ;; esac; \
	if [ "$$(realpath -m "$$pkg_dir")" != "$$(realpath -m '$(REPO_ROOT)/pkg')" ]; then \
		echo "notice: PKG_DIR=$$pkg_dir is not the pkg submodule; its commit is not checked" >&2; \
	elif ! command -v git >/dev/null 2>&1 || ! git -C '$(REPO_ROOT)' rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
		echo "refusing: cannot check that pkg/ is at the pinned commit (git is missing or $(REPO_ROOT) is not a Git checkout); set PKG_DIR to an extracted package directory to skip this check" >&2; exit 1; \
	else \
		state="$$(git -C '$(REPO_ROOT)' submodule status -- pkg 2>/dev/null | cut -c1)"; \
		case "$$state" in \
			-|+|U) echo "refusing: pkg/ is not at the commit this checkout pins (git submodule status: '$$state'); run: git submodule update --init  (then make -C deploy init again)" >&2; exit 1 ;; \
		esac; \
	fi
	$(COMPOSE) up -d --wait postgres elasticsearch redis-broker redis-cache
	$(COMPOSE) run --rm -T init

admin-password: ## Set the admin password from the admin_password secret (first install, rotation)
	$(COMPOSE) run --rm --no-deps -T web manage set_admin_password

manage: ## Run a management command, interactive: make -C deploy manage ARGS="changepassword admin"
	$(COMPOSE) run --rm --no-deps web manage $(ARGS)

load-snapshot: ## Rehearsal only: replace the data with a dev snapshot (SNAPSHOT=/path) or an aside directory (RESTORE_BEFORE=/path), CONFIRM=yes
	COMPOSE='$(COMPOSE)' ENV_FILE='$(ENV_FILE)' CONFIRM='$(CONFIRM)' RESTORE_BEFORE='$(RESTORE_BEFORE)' \
		$(abspath $(dir $(lastword $(MAKEFILE_LIST))))/scripts/load-snapshot.sh '$(SNAPSHOT)'

# Backups (BACKUP.md). TAG: nightly (retention and repository check), manual or
# pre-update (the blocking backup before an update: non-zero exit stops it).
TAG ?= manual
BACKUP_ENV = COMPOSE='$(COMPOSE)' ENV_FILE='$(ENV_FILE)' METRICS_TEXTFILE_DIR="$(call envval,METRICS_TEXTFILE_DIR)"

backup-init: ## Once per host: create the restic repository, or check that it opens (idempotent)
	$(BACKUP_ENV) $(SCRIPTS_DIR)/backup.sh --init

backup: ## Back up the database, the uploads and the secrets: make -C deploy backup [TAG=nightly|manual|pre-update]
	$(BACKUP_ENV) $(SCRIPTS_DIR)/backup.sh --tag '$(TAG)'

# Host metrics for the node_exporter textfile collector (host-metrics.sh); the
# systemd timers of deploy/systemd run these two targets.
HOST_METRICS_ENV = COMPOSE_PROJECT=manuspectrum METRICS_TEXTFILE_DIR="$(call envval,METRICS_TEXTFILE_DIR)"

container-metrics: ## Write the container metrics (up, health, restarts, OOM kills, memory); the timer runs it every 30 s
	$(HOST_METRICS_ENV) $(SCRIPTS_DIR)/host-metrics.sh containers

disk-usage: ## Write the size of the uploads, restic repository, dumps and nginx logs (never du of a mount root); the timer runs it hourly
	$(HOST_METRICS_ENV) DISK_USAGE_AREAS="media=$(call envval,MEDIA_HOST_DIR) restic=$(call envval,RESTIC_REPOSITORY_DIR) dumps=$(call envval,BACKUP_DUMP_DIR) nginx_logs=$(call envval,NGINX_LOG_HOST_DIR)" \
		$(SCRIPTS_DIR)/host-metrics.sh disk

restore-test: ## Prove the latest backup restores into a scratch database: make -C deploy restore-test [RESTIC_SNAPSHOT=<id>]
	$(BACKUP_ENV) $(SCRIPTS_DIR)/restore-test.sh$(if $(RESTIC_SNAPSHOT), --snapshot '$(RESTIC_SNAPSHOT)')

restore: ## Replace the database and the uploads from a backup: make -C deploy restore RESTIC_SNAPSHOT=<id|latest> | ASIDE=<dir> CONFIRM=yes ERASURES_CHECKED=yes
	COMPOSE='$(COMPOSE)' ENV_FILE='$(ENV_FILE)' CONFIRM='$(CONFIRM)' ERASURES_CHECKED='$(ERASURES_CHECKED)' \
		RESTIC_SNAPSHOT='$(RESTIC_SNAPSHOT)' ASIDE='$(ASIDE)' $(SCRIPTS_DIR)/restore.sh

restore-files: ## Pull files from a backup into a separate directory: make -C deploy restore-files INCLUDE=/backup/... TARGET=/path [RESTIC_SNAPSHOT=<id>]
	COMPOSE='$(COMPOSE)' ENV_FILE='$(ENV_FILE)' RESTIC_SNAPSHOT='$(RESTIC_SNAPSHOT)' INCLUDE='$(INCLUDE)' \
		TARGET='$(TARGET)' $(SCRIPTS_DIR)/restore-files.sh

restic: ## Run restic on the repository, interactive: make -C deploy restic ARGS="snapshots"
	$(BACKUP_ENV) $(SCRIPTS_DIR)/backup.sh --restic $(ARGS)

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

# The monitoring services run under the `observability` profile. COMPOSE_PROFILES
# in the env file switches it on for every command; naming the services here
# enables it for these two targets even when it is empty.
OBSERVABILITY_SERVICES := prometheus alertmanager grafana node-exporter postgres-exporter redis-exporter blackbox-exporter

monitoring-init: ## Once per host, with postgres up: create or update the ms_monitor role and pg_stat_statements (password from pg_monitor_password)
	COMPOSE='$(COMPOSE)' ENV_FILE='$(ENV_FILE)' SECRETS_DIR='$(SECRETS_DIR)' $(SCRIPTS_DIR)/monitoring-init.sh

observability-on: ## Start the monitoring services and wait until they are healthy
	$(COMPOSE) --profile observability up -d --wait $(OBSERVABILITY_SERVICES)

observability-off: ## Stop and remove the monitoring containers (volumes kept); empty COMPOSE_PROFILES in .env to keep them off
	$(COMPOSE) --profile observability rm --stop --force $(OBSERVABILITY_SERVICES)
	@echo "Volumes kept. Set COMPOSE_PROFILES= in $(ENV_FILE) so that 'make up' does not start them again."

# amtool inside the running container: no published port, no host install.
AMTOOL = $(COMPOSE) --profile observability exec -T alertmanager amtool --alertmanager.url=http://127.0.0.1:9093

# Alertmanager reads ALERT_EMAILS, ALERT_EMAIL_FROM, PUBLIC_HOST and the EMAIL_* relay from
# its environment, fixed when the container is created, so a /-/reload could
# not see a changed .env. The values are checked on the host with the same
# render.sh first (a bad list must not take the running instance down), then
# `up` recreates only this container when its environment changed; the
# silences and the notification log live on a volume and survive.
alert-recipients: ## After editing ALERT_EMAILS (or the sender or relay) in .env: validate, recreate alertmanager, wait until ready
	@ALERT_EMAILS="$(call envval,ALERT_EMAILS)" ALERT_EMAIL_FROM="$(call envval,ALERT_EMAIL_FROM)" \
		PUBLIC_HOST="$(call envval,PUBLIC_HOST)" EMAIL_HOST="$(call envval,EMAIL_HOST)" EMAIL_PORT="$(call envval,EMAIL_PORT)" \
		EMAIL_USE_TLS="$(call envval,EMAIL_USE_TLS)" EMAIL_HOST_USER="$(call envval,EMAIL_HOST_USER)" \
		ALERTMANAGER_DIR='$(COMPOSE_DIR)/observability/alertmanager' ALERTMANAGER_VALIDATE_ONLY=1 \
		sh '$(COMPOSE_DIR)/observability/alertmanager/render.sh' \
		|| { echo "alert-recipients: fix $(ENV_FILE); alertmanager was left running unchanged" >&2; exit 1; }
	$(COMPOSE) --profile observability up -d --no-deps --wait alertmanager

alert-test: ## Fire a critical AlertTest for 5 minutes: an e-mail must reach ALERT_EMAILS (Mailpit in the rehearsal)
	$(AMTOOL) alert add AlertTest severity=critical service=monitoring \
		--annotation=summary='"Test alert"' --annotation=description='"Raised by make alert-test; no action needed."' \
		--annotation=runbook_url='"https://github.com/CRC-Centre-Recherche-Conservation/ManuSpectrum/blob/main/deploy/runbooks/monitoring.md"' \
		--end="$$(date -u -d '+5 minutes' +%Y-%m-%dT%H:%M:%SZ)"

alerts: ## Alerts Alertmanager holds now
	$(AMTOOL) alert query

silence: ## Silence for maintenance: make silence ARGS='alertname=DiskUsageHigh --duration=2h --comment="why"'
	@[ -n "$(ARGS)" ] || { echo "usage: make silence ARGS='matcher... --duration=2h --comment=\"why\"'" >&2; exit 1; }
	$(AMTOOL) silence add $(ARGS)

# A new install raises, until the first backup, the first restore test and the
# first run of the systemd timers, alerts that say nothing about a fault.
silence-fresh-install: ## Silence for 48 h the alerts a new install raises before its first backup, restore test and timers
	$(AMTOOL) silence add 'alertname=~"BackupMissing|RestoreTestMissing|HostMetricsStale|DiskUsageStale|ContainerMissing"' \
		--duration=48h --comment="fresh install: first backup, restore test and timers pending"

# The monthly report (scripts/monthly-report.py, Python standard library only)
# runs in a throwaway container of the application image on the Compose
# network, where `prometheus` and the SMTP relay resolve; the relay settings
# come from the env file the container already reads. The script is mounted
# read-only. The content, workflow and bulk import sections come from
# `manage.py activity_summary`, which the script runs itself in the same
# container (read-only SQL, aggregates as JSON; no metrics files, no statement
# timeout). Exit 1: sent with a section "données indisponibles".
monthly-report: ## Send the report of the previous month to ALERT_EMAILS (the timer runs it on the 1st at 08:00)
	$(COMPOSE) run --rm --no-deps -T --entrypoint python3 \
		-v '$(SCRIPTS_DIR)/monthly-report.py:/monthly-report.py:ro' \
		-e ALERT_EMAILS="$(call envval,ALERT_EMAILS)" -e ALERT_EMAIL_FROM="$(call envval,ALERT_EMAIL_FROM)" \
		web -I /monthly-report.py \
		--activity-command "env -u PROMETHEUS_MULTIPROC_DIR PG_STATEMENT_TIMEOUT_MS=0 python manage.py activity_summary" $(ARGS)

report-test: ## Send the report now to ALERT_EMAILS to check the chain: make -C deploy report-test [ARGS="--month YYYY-MM"]
	$(MAKE) --no-print-directory monthly-report

smoke: ## Read-only checks of the running stack
	$(COMPOSE_DIR)/smoke.sh check

nginx-test: ## Check the nginx configuration of the running container
	$(COMPOSE) exec nginx nginx -t

nginx-reload: ## Reload nginx (new certificate or configuration) after checking it
	$(COMPOSE) exec nginx nginx -t
	$(COMPOSE) exec nginx nginx -s reload

certs-local: ## CERT_MODE=local: make the rehearsal CA and a certificate for DOMAIN_NAMES in CERTS_DIR
	@[ "$(call envval,CERT_MODE)" = local ] || { echo "CERT_MODE is not local in $(ENV_FILE)" >&2; exit 1; }
	@certs="$(call envval,CERTS_DIR)"; names="$(call envval,DOMAIN_NAMES)"; \
	[ -n "$$certs" ] && [ -n "$$names" ] || { echo "set CERTS_DIR and DOMAIN_NAMES in $(ENV_FILE)" >&2; exit 1; }; \
	install -d -m 0755 "$$certs/acme-webroot" "$$certs/live" && \
	CA_DIR="$$certs/ca" $(abspath $(dir $(lastword $(MAKEFILE_LIST))))/certs/make-local-ca.sh "$$certs/live" $$names

# Certbot arguments of cert-init, e.g. CERTBOT_ARGS=--force-renewal to replace a
# staging certificate by a production one after changing ACME_SERVER.
CERTBOT_ARGS ?=
CERTBOT := $(COMPOSE) --profile acme run --rm --no-deps -T certbot
CERT_FILE = $(call envval,CERTS_DIR)/live/fullchain.pem

cert-init: ## CERT_MODE=acme: placeholder certificate, nginx up, first certificate, reload
	@[ "$(call envval,CERT_MODE)" = acme ] || { echo "CERT_MODE is not acme in $(ENV_FILE)" >&2; exit 1; }
	@[ -n "$(call envval,ACME_EMAIL)" ] || { echo "set ACME_EMAIL in $(ENV_FILE)" >&2; exit 1; }
	@certs="$(call envval,CERTS_DIR)"; names="$(call envval,DOMAIN_NAMES)"; \
	[ -n "$$certs" ] && [ -n "$$names" ] || { echo "set CERTS_DIR and DOMAIN_NAMES in $(ENV_FILE)" >&2; exit 1; }; \
	install -d -m 0755 "$$certs/acme-webroot" "$$certs/live" && install -d -m 0700 "$$certs/letsencrypt" && \
	{ [ -e "$$certs/live/fullchain.pem" ] || $(abspath $(dir $(lastword $(MAKEFILE_LIST))))/certs/make-local-ca.sh --self-signed "$$certs/live" $$names; } && \
	$(COMPOSE) up -d --no-deps --wait nginx && \
	domains=""; for n in $$names; do domains="$$domains -d $$n"; done && \
	$(CERTBOT) certonly --webroot -w /certs/acme-webroot --cert-name manuspectrum $$domains \
		--email "$(call envval,ACME_EMAIL)" --agree-tos --no-eff-email --non-interactive \
		--server "$(call envval,ACME_SERVER)" --deploy-hook /hooks/deploy-hook.sh $(CERTBOT_ARGS) && \
	$(MAKE) --no-print-directory nginx-reload

# The deploy hook rewrites live/fullchain.pem only when a certificate was
# renewed: nginx is reloaded when the file changed, even when certbot exits
# non-zero (another lineage failed after one was installed), and the target
# then exits with certbot's status.
cert-renew: ## CERT_MODE=acme: renew the certificate when due, reload nginx if it changed
	@[ "$(call envval,CERT_MODE)" = acme ] || { echo "CERT_MODE is not acme in $(ENV_FILE)" >&2; exit 1; }
	@before=$$(cksum < "$(CERT_FILE)" 2>/dev/null || true); \
	rc=0; $(CERTBOT) renew --non-interactive || rc=$$?; \
	after=$$(cksum < "$(CERT_FILE)" 2>/dev/null || true); \
	if [ "$$before" != "$$after" ]; then $(MAKE) --no-print-directory nginx-reload || { [ "$$rc" -ne 0 ] || rc=1; }; else echo "certificate unchanged"; fi; \
	exit $$rc
