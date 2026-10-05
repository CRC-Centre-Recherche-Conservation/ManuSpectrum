"""Settings of the container image (DJANGO_SETTINGS_MODULE=manuspectrum.settings_docker).

Imports manuspectrum.settings, then overrides it from the environment on the
model of arches/settings_docker.py: a required variable that is missing raises
ImproperlyConfigured at import, so a container never starts half-configured.
A secret NAME is read from the file named by NAME_FILE when that variable is
set (Compose secrets), else from NAME itself.

What must never depend on the environment is fixed here: DEBUG, the cookie
flags, the proxy header, the media and static roots, JSON logs on stdout (see
observability/logging.py). settings_local.py is a development file: the image does not ship it and
this module refuses to run when one was imported.

Redis runs as two instances. The broker (Celery, IIIF sign-ins) never evicts;
the cache evicts least-recently-used keys. Each alias of settings.CACHES is
pointed at its instance in place; KEY_PREFIX and the other entries are kept.
"""

import os
import sys

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F401,F403
from .observability.logging import FORMATS, build_logging
from .settings import (
    APP_VERSION,
    CACHES,
    DATABASES,
    ELASTICSEARCH_CONNECTION_OPTIONS,
    ELASTICSEARCH_PREFIX,
    EXTRA_EMAIL_CONTEXT,
    UPLOADED_FILES_DIR,
)

if sys.modules.get("manuspectrum.settings_local") or sys.modules.get("settings_local"):
    raise ImproperlyConfigured(
        "settings_local.py was imported; it must not exist in the image"
    )


def get_env_variable(name):
    """Return the environment variable `name`; ImproperlyConfigured when it is unset."""
    try:
        return os.environ[name]
    except KeyError:
        raise ImproperlyConfigured(f"Set the {name} environment variable") from None


def get_optional_env_variable(name, default=None):
    return os.environ.get(name, default)


def read_secret(name):
    """Return the secret `name`: the file `<name>_FILE` names, else the variable `name`.

    Surrounding whitespace is stripped. Error messages name the variable and
    the path, never the value.
    """
    path = os.environ.get(f"{name}_FILE")
    if not path:
        return get_env_variable(name)
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError as error:
        raise ImproperlyConfigured(
            f"Cannot read {name}_FILE ({path}): {error.strerror}"
        ) from None


def env_bool(name, default):
    """Return the boolean variable `name`: true/false, yes/no, on/off or 1/0."""
    value = get_optional_env_variable(name)
    if value is None or value.strip() == "":
        return default
    value = value.strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    raise ImproperlyConfigured(f"{name} must be true or false, not {value!r}")


DEBUG = False

SECRET_KEY = read_secret("MANUSPECTRUM_SECRET_KEY")
if SECRET_KEY.startswith("django-insecure-") or len(SECRET_KEY) < 50:
    raise ImproperlyConfigured(
        "MANUSPECTRUM_SECRET_KEY must be a generated key of at least 50 characters"
    )

DOMAIN_NAMES = get_env_variable("DOMAIN_NAMES").split()
if not DOMAIN_NAMES:
    raise ImproperlyConfigured("Set at least one name in DOMAIN_NAMES")
# web: the Compose service name, resolvable only on the internal network; probes send Host: web.
ALLOWED_HOSTS = DOMAIN_NAMES + ["web"]
CSRF_TRUSTED_ORIGINS = [f"https://{name}" for name in DOMAIN_NAMES]

PUBLIC_SERVER_ADDRESS = get_env_variable("PUBLIC_SERVER_ADDRESS")
if not PUBLIC_SERVER_ADDRESS.startswith("https://"):
    raise ImproperlyConfigured("PUBLIC_SERVER_ADDRESS must be an https:// URL")
# Compose appends `iiifserver` to this value without a separator.
if not PUBLIC_SERVER_ADDRESS.endswith("/"):
    raise ImproperlyConfigured("PUBLIC_SERVER_ADDRESS must end with a slash")
ARCHES_NAMESPACE_FOR_DATA_EXPORT = PUBLIC_SERVER_ADDRESS
EXTRA_EMAIL_CONTEXT = {
    **EXTRA_EMAIL_CONTEXT,
    "site_url": PUBLIC_SERVER_ADDRESS.rstrip("/"),
}

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
# nginx sets X-Forwarded-Proto; the Arches deployment guide's example names X-Forwarded-Protocol.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "SAMEORIGIN"
SECURE_SSL_REDIRECT = False


def timeout_ms(name, default):
    """Return the environment variable `name` as milliseconds: `default` when unset, 0 for no timeout."""
    value = get_optional_env_variable(name, default).strip()
    try:
        timeout = int(value)
    except ValueError:
        timeout = -1
    if timeout < 0:
        raise ImproperlyConfigured(
            f"{name} must be a number of milliseconds, not {value!r}"
        )
    return timeout


# Compose sets both for `web` alone: gthread request threads are not bounded by
# gunicorn's timeout, so PostgreSQL bounds each statement and each idle
# transaction of the connection. Worker, beat and management commands run
# without either.
DATABASE_OPTIONS = dict(DATABASES["default"]["OPTIONS"])
for _setting, _variable, _default in (
    ("statement_timeout", "PG_STATEMENT_TIMEOUT_MS", "60000"),
    (
        "idle_in_transaction_session_timeout",
        "PG_IDLE_IN_TRANSACTION_TIMEOUT_MS",
        "60000",
    ),
):
    _value = timeout_ms(_variable, _default)
    if _value:
        DATABASE_OPTIONS["options"] += f" -c {_setting}={_value}"

DATABASES = {
    "default": {
        **DATABASES["default"],
        "OPTIONS": DATABASE_OPTIONS,
        "NAME": get_env_variable("PGDBNAME"),
        "USER": get_env_variable("PGUSERNAME"),
        "PASSWORD": read_secret("PGPASSWORD"),
        "HOST": get_env_variable("PGHOST"),
        "PORT": get_env_variable("PGPORT"),
    }
}

ELASTICSEARCH_HTTP_PORT = get_env_variable("ESPORT")
ELASTICSEARCH_HOSTS = [
    {
        "scheme": "http",
        "host": get_env_variable("ESHOST"),
        "port": int(ELASTICSEARCH_HTTP_PORT),
    }
]
ELASTICSEARCH_CONNECTION_OPTIONS = {
    **ELASTICSEARCH_CONNECTION_OPTIONS,
    "basic_auth": ("elastic", read_secret("ELASTIC_PASSWORD")),
}
ELASTICSEARCH_PREFIX = get_optional_env_variable(
    "ELASTICSEARCH_PREFIX", ELASTICSEARCH_PREFIX
)

REDIS_BROKER_URL = get_env_variable("REDIS_BROKER_URL").rstrip("/")
REDIS_CACHE_URL = get_env_variable("REDIS_CACHE_URL").rstrip("/")
CELERY_BROKER_URL = f"{REDIS_BROKER_URL}/0"
CACHES["iiif_auth"]["LOCATION"] = f"{REDIS_BROKER_URL}/3"
CACHES["default"]["LOCATION"] = f"{REDIS_CACHE_URL}/0"
CACHES["user_permission"]["LOCATION"] = f"{REDIS_CACHE_URL}/1"

CANTALOUPE_HTTP_ENDPOINT = "http://{}:{}/".format(
    get_env_variable("CANTALOUPE_HOST"), get_env_variable("CANTALOUPE_PORT")
)

MEDIA_ROOT = "/srv/media"
CANTALOUPE_DIR = os.path.join(MEDIA_ROOT, UPLOADED_FILES_DIR)
STATIC_ROOT = "/app/static"
RESOURCE_IMPORT_LOG = "/tmp/resource_import.log"

CONTACT_EMAIL = get_env_variable("CONTACT_EMAIL")
EMAIL_HOST = get_env_variable("EMAIL_HOST")
EMAIL_PORT = int(get_env_variable("EMAIL_PORT"))
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", False)
EMAIL_HOST_USER = get_optional_env_variable("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = (
    read_secret("EMAIL_HOST_PASSWORD")
    if "EMAIL_HOST_PASSWORD_FILE" in os.environ or "EMAIL_HOST_PASSWORD" in os.environ
    else ""
)
DEFAULT_FROM_EMAIL = get_optional_env_variable("DEFAULT_FROM_EMAIL") or CONTACT_EMAIL
if not DEFAULT_FROM_EMAIL:
    raise ImproperlyConfigured("Set DEFAULT_FROM_EMAIL or CONTACT_EMAIL")
SERVER_EMAIL = DEFAULT_FROM_EMAIL
ADMINS = [("", address) for address in get_optional_env_variable("ADMINS", "").split()]

CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = get_optional_env_variable("CORS_ALLOWED_ORIGINS", "").split()

BIBLISSIMA_ASYNC_INDEXING = env_bool("BIBLISSIMA_ASYNC_INDEXING", True)

# JSON on stdout; MS_LOG_FORMAT=text for a human at a terminal.
MS_LOG_FORMAT = get_optional_env_variable("MS_LOG_FORMAT", "json").strip().lower()
if MS_LOG_FORMAT not in FORMATS:
    raise ImproperlyConfigured(
        f"MS_LOG_FORMAT must be json or text, not {MS_LOG_FORMAT!r}"
    )
LOGGING = build_logging(
    MS_LOG_FORMAT,
    environment=get_optional_env_variable("DEPLOY_ENVIRONMENT", "development"),
    version=get_optional_env_variable("MS_VERSION") or str(APP_VERSION),
)
# The worker keeps LOGGING: Celery leaves a root logger that already has handlers alone.
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
