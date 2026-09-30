# ManuSpectrum image. Build context: the repository root.
#   docker build -f deploy/docker/Dockerfile .
# python-deps: the virtualenv from uv.lock (without uv's world-writable .lock),
#              frontend configuration generated
# frontend:    npm ci and the production webpack build (Node 24)
# collect:     collectstatic into /app/static and its .build-id
# runtime:     no compiler, no Node, no uv, no pip; runs under any uid on a read-only root

ARG PYTHON_IMAGE=python:3.13-slim-trixie@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b
ARG NODE_IMAGE=node:24-trixie-slim@sha256:8ec5d7557396cfe32d21c3f9c13072355ceab22b584578ca4bb28af31120cffe
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.20@sha256:100047e74f30778ab704942321a09750d6158739573ff58bf3924085cc6cd2d8

FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE} AS python-deps
ENV PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3.13 \
    PATH=/opt/venv/bin:$PATH
# Debian package versions are fixed by the base image digest.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev libgdal36 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --group prod --no-install-project \
    && rm -f /opt/venv/.lock
COPY manage.py ./
COPY manuspectrum ./manuspectrum
COPY deploy/docker/placeholder.env /tmp/placeholder.env
RUN set -a && . /tmp/placeholder.env && set +a \
    && python -c "import django; django.setup()" \
    && test -s frontend_configuration/webpack-metadata.json

FROM ${NODE_IMAGE} AS frontend
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system url."https://github.com/".insteadOf "ssh://git@github.com/"
ENV NODE_OPTIONS=--max-old-space-size=6144
WORKDIR /app
COPY package.json package-lock.json ./
RUN node --version | grep -q '^v24\.' \
    && npm ci --no-audit --no-fund
COPY --from=python-deps /opt/venv /opt/venv
COPY --from=python-deps /app /app
COPY .babelrc .browserslistrc tsconfig.json eslint.config.mjs .prettierrc .stylelintrc.json \
     gettext.config.js webpack.project.js ./
COPY webpack ./webpack
RUN npm run build_production \
    && npm prune --omit=dev --no-audit --no-fund

FROM python-deps AS collect
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
COPY --from=frontend /app/manuspectrum/media/build ./manuspectrum/media/build
COPY --from=frontend /app/webpack/webpack-stats.json ./webpack/webpack-stats.json
COPY --from=frontend /app/node_modules ./node_modules
RUN set -a && . /tmp/placeholder.env && set +a \
    && python manage.py collectstatic --noinput \
    && python -m compileall -q manuspectrum \
    && find static -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum \
        | sha256sum | cut -c1-16 > static/.build-id

FROM ${PYTHON_IMAGE} AS runtime
LABEL org.opencontainers.image.title="ManuSpectrum" \
      org.opencontainers.image.source="https://github.com/CRC-Centre-Recherche-Conservation/ManuSpectrum" \
      org.opencontainers.image.licenses="AGPL-3.0-only"
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app \
    HOME=/tmp \
    DJANGO_SETTINGS_MODULE=manuspectrum.settings_docker
# Debian security fixes land before the official image is rebuilt: upgrade the
# runtime packages at build time (the digest above only fixes the starting point).
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends libgdal36 libpq5 postgresql-client curl \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /usr/local/lib/python3.13/site-packages/pip \
              /usr/local/lib/python3.13/site-packages/pip-*.dist-info \
              /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13 \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent \
       --shell /usr/sbin/nologin app \
    && install -d -m 1777 /srv/static /var/lib/celery \
    && install -d -m 0755 /srv/media
COPY --from=collect /opt/venv /opt/venv
COPY --from=collect /app/manage.py /app/manage.py
# Arches' compatibility check reads the project's requirements from it: the
# project is not installed as a package (uv sync --no-install-project).
COPY --from=collect /app/pyproject.toml /app/pyproject.toml
COPY --from=collect /app/manuspectrum /app/manuspectrum
COPY --from=collect /app/webpack/webpack-stats.json /app/webpack/webpack-stats.json
COPY --from=collect /app/static /app/static
COPY deploy/docker/gunicorn.conf.py /app/gunicorn.conf.py
COPY --chmod=0755 deploy/docker/entrypoint.sh /usr/local/bin/entrypoint
COPY --chmod=0755 deploy/docker/publish-static.sh /usr/local/bin/publish-static
RUN ln -s /tmp/frontend_configuration /app/frontend_configuration
USER 10001:10001
WORKDIR /app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=300s --retries=3 \
    CMD ["sh", "-c", "curl -fsS -o /dev/null -H 'Host: web' http://127.0.0.1:8000/healthz || exit 1"]
ENTRYPOINT ["entrypoint"]
CMD ["web"]
