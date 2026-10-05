"""Tests of manuspectrum.settings_docker.

Each test imports the module in a fresh interpreter whose environment is the
test's own, never the one of the test run. settings_local.py is made
unimportable in that interpreter, as it is absent from the image.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from unittest import skipUnless

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent

BASE_ENV = {
    "MANUSPECTRUM_SECRET_KEY": "test-key-not-a-secret-" + "0123456789" * 4,
    "DOMAIN_NAMES": "manuspectrum.test www.manuspectrum.test",
    "PUBLIC_SERVER_ADDRESS": "https://manuspectrum.test/",
    "PGDBNAME": "manuspectrum",
    "PGUSERNAME": "postgres",
    "PGPASSWORD": "pg-test",
    "PGHOST": "postgres",
    "PGPORT": "5432",
    "ESHOST": "elasticsearch",
    "ESPORT": "9200",
    "ELASTIC_PASSWORD": "es-test",
    "REDIS_BROKER_URL": "redis://redis-broker:6379",
    "REDIS_CACHE_URL": "redis://redis-cache:6379/",
    "CANTALOUPE_HOST": "cantaloupe",
    "CANTALOUPE_PORT": "8182",
    "CONTACT_EMAIL": "contact@manuspectrum.test",
    "EMAIL_HOST": "smtp.manuspectrum.test",
    "EMAIL_PORT": "25",
}

NAMES = [
    "DEBUG",
    "SECRET_KEY",
    "SESSION_COOKIE_SECURE",
    "CSRF_COOKIE_SECURE",
    "SESSION_COOKIE_HTTPONLY",
    "SECURE_PROXY_SSL_HEADER",
    "SECURE_SSL_REDIRECT",
    "ALLOWED_HOSTS",
    "CSRF_TRUSTED_ORIGINS",
    "PUBLIC_SERVER_ADDRESS",
    "ARCHES_NAMESPACE_FOR_DATA_EXPORT",
    "MEDIA_ROOT",
    "CANTALOUPE_DIR",
    "STATIC_ROOT",
    "CORS_ALLOW_ALL_ORIGINS",
    "CORS_ALLOWED_ORIGINS",
    "DATABASES",
    "ELASTICSEARCH_HOSTS",
    "ELASTICSEARCH_HTTP_PORT",
    "ELASTICSEARCH_CONNECTION_OPTIONS",
    "ELASTICSEARCH_PREFIX",
    "CELERY_BROKER_URL",
    "CACHES",
    "CACHE_CODE_VERSION",
    "CANTALOUPE_HTTP_ENDPOINT",
    "CONTACT_EMAIL",
    "DEFAULT_FROM_EMAIL",
    "EMAIL_HOST",
    "EMAIL_PORT",
    "EMAIL_USE_TLS",
    "EMAIL_HOST_USER",
    "EMAIL_HOST_PASSWORD",
    "INSTALLED_APPS",
    "MIDDLEWARE",
    "LOGGING",
    "BIBLISSIMA_ASYNC_INDEXING",
]

PROBE = textwrap.dedent("""
    import json, sys, types
    sys.modules["manuspectrum.settings_local"] = None
    sys.modules["settings_local"] = None
    if {fake_local!r}:
        sys.modules["manuspectrum.settings_local"] = types.ModuleType("manuspectrum.settings_local")
    try:
        import manuspectrum.settings_docker as s
    except Exception as error:
        print(json.dumps({{"error": type(error).__name__, "message": str(error)}}))
    else:
        values = {{name: getattr(s, name) for name in {names!r}}}
        values["SITE_URL"] = s.EXTRA_EMAIL_CONTEXT["site_url"]
        print(json.dumps(values, default=str))
    """)


def load(env, fake_local=False):
    """Import settings_docker under `env` alone and return its values or its error."""
    with tempfile.TemporaryDirectory() as home:
        result = subprocess.run(
            [sys.executable, "-c", PROBE.format(fake_local=fake_local, names=NAMES)],
            env={
                "PATH": os.environ["PATH"],
                "HOME": home,
                "PYTHONPATH": str(ROOT),
                "DJANGO_SETTINGS_MODULE": "manuspectrum.settings_docker",
                **env,
            },
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
        )
    if result.returncode != 0:
        raise AssertionError(result.stderr[-3000:])
    return json.loads(result.stdout.strip().splitlines()[-1])


class SettingsDockerTests(SimpleTestCase):
    def assertRefused(self, env, fragment, **options):
        values = load(env, **options)
        self.assertEqual(values.get("error"), "ImproperlyConfigured", values)
        self.assertIn(fragment, values["message"])

    def test_missing_required_variable_is_refused(self):
        for name in (
            "MANUSPECTRUM_SECRET_KEY",
            "DOMAIN_NAMES",
            "PUBLIC_SERVER_ADDRESS",
            "PGHOST",
            "REDIS_BROKER_URL",
            "EMAIL_HOST",
        ):
            with self.subTest(name=name):
                env = dict(BASE_ENV)
                del env[name]
                self.assertRefused(env, name)

    def test_development_or_short_secret_key_is_refused(self):
        for key in ("django-insecure-" + "x" * 50, "short-key"):
            with self.subTest(key=key[:20]):
                self.assertRefused(
                    dict(BASE_ENV, MANUSPECTRUM_SECRET_KEY=key),
                    "MANUSPECTRUM_SECRET_KEY",
                )

    def test_secret_file_wins_over_the_variable(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as handle:
            handle.write("from-file\n")
        self.addCleanup(os.unlink, handle.name)
        values = load(dict(BASE_ENV, PGPASSWORD_FILE=handle.name))
        self.assertEqual(values["DATABASES"]["default"]["PASSWORD"], "from-file")

    def test_unreadable_secret_file_is_refused(self):
        self.assertRefused(
            dict(BASE_ENV, PGPASSWORD_FILE="/nonexistent/pg_password"),
            "PGPASSWORD_FILE",
        )

    def test_plain_http_public_address_is_refused(self):
        self.assertRefused(
            dict(BASE_ENV, PUBLIC_SERVER_ADDRESS="http://manuspectrum.test/"),
            "PUBLIC_SERVER_ADDRESS",
        )

    def test_public_address_without_a_trailing_slash_is_refused(self):
        self.assertRefused(
            dict(BASE_ENV, PUBLIC_SERVER_ADDRESS="https://manuspectrum.test"),
            "end with a slash",
        )

    def test_settings_local_is_refused(self):
        self.assertRefused(BASE_ENV, "settings_local", fake_local=True)

    def test_production_values_are_fixed(self):
        values = load(BASE_ENV)
        self.assertIs(values["DEBUG"], False)
        self.assertIs(values["SESSION_COOKIE_SECURE"], True)
        self.assertIs(values["CSRF_COOKIE_SECURE"], True)
        self.assertIs(values["SESSION_COOKIE_HTTPONLY"], True)
        self.assertEqual(
            values["SECURE_PROXY_SSL_HEADER"], ["HTTP_X_FORWARDED_PROTO", "https"]
        )
        self.assertIs(values["SECURE_SSL_REDIRECT"], False)
        self.assertEqual(values["MEDIA_ROOT"], "/srv/media")
        self.assertEqual(values["CANTALOUPE_DIR"], "/srv/media/uploadedfiles")
        self.assertEqual(values["STATIC_ROOT"], "/app/static")
        self.assertIs(values["CORS_ALLOW_ALL_ORIGINS"], False)
        self.assertEqual(values["CORS_ALLOWED_ORIGINS"], [])
        self.assertFalse([app for app in values["INSTALLED_APPS"] if "silk" in app])
        self.assertFalse([m for m in values["MIDDLEWARE"] if "silk" in m])

    def test_hosts_origins_and_public_address_come_from_the_environment(self):
        values = load(BASE_ENV)
        self.assertEqual(
            values["ALLOWED_HOSTS"],
            ["manuspectrum.test", "www.manuspectrum.test", "web"],
        )
        self.assertEqual(
            values["CSRF_TRUSTED_ORIGINS"],
            ["https://manuspectrum.test", "https://www.manuspectrum.test"],
        )
        self.assertEqual(values["PUBLIC_SERVER_ADDRESS"], "https://manuspectrum.test/")
        self.assertEqual(
            values["ARCHES_NAMESPACE_FOR_DATA_EXPORT"], "https://manuspectrum.test/"
        )
        self.assertEqual(values["SITE_URL"], "https://manuspectrum.test")

    def test_each_redis_alias_points_at_its_instance(self):
        values = load(BASE_ENV)
        caches = values["CACHES"]
        self.assertEqual(values["CELERY_BROKER_URL"], "redis://redis-broker:6379/0")
        self.assertEqual(caches["iiif_auth"]["LOCATION"], "redis://redis-broker:6379/3")
        self.assertEqual(caches["iiif_auth"]["KEY_PREFIX"], "ms-iiif-auth")
        self.assertEqual(caches["default"]["LOCATION"], "redis://redis-cache:6379/0")
        self.assertEqual(
            caches["default"]["KEY_PREFIX"], f"ms:{values['CACHE_CODE_VERSION']}"
        )
        self.assertEqual(
            caches["user_permission"]["LOCATION"], "redis://redis-cache:6379/1"
        )

    def test_services_come_from_the_environment(self):
        values = load(BASE_ENV)
        database = values["DATABASES"]["default"]
        self.assertEqual(database["ENGINE"], "django.contrib.gis.db.backends.postgis")
        self.assertEqual(database["POSTGIS_TEMPLATE"], "template_postgis")
        self.assertEqual(
            (
                database["NAME"],
                database["USER"],
                database["PASSWORD"],
                database["HOST"],
            ),
            ("manuspectrum", "postgres", "pg-test", "postgres"),
        )
        self.assertIn("cursor_tuple_fraction=1", database["OPTIONS"]["options"])
        self.assertEqual(
            values["ELASTICSEARCH_HOSTS"],
            [{"scheme": "http", "host": "elasticsearch", "port": 9200}],
        )
        self.assertEqual(
            values["ELASTICSEARCH_CONNECTION_OPTIONS"]["basic_auth"],
            ["elastic", "es-test"],
        )
        self.assertEqual(values["ELASTICSEARCH_HTTP_PORT"], "9200")
        self.assertEqual(values["ELASTICSEARCH_PREFIX"], "manuspectrum")
        self.assertEqual(values["CANTALOUPE_HTTP_ENDPOINT"], "http://cantaloupe:8182/")

    def test_mail_defaults_suit_a_relay_without_tls_or_authentication(self):
        values = load(BASE_ENV)
        self.assertEqual(
            (values["EMAIL_HOST"], values["EMAIL_PORT"]), ("smtp.manuspectrum.test", 25)
        )
        self.assertIs(values["EMAIL_USE_TLS"], False)
        self.assertEqual(
            (values["EMAIL_HOST_USER"], values["EMAIL_HOST_PASSWORD"]), ("", "")
        )
        self.assertEqual(values["DEFAULT_FROM_EMAIL"], "contact@manuspectrum.test")

    def test_booleans_are_parsed_strictly(self):
        self.assertIs(load(dict(BASE_ENV, EMAIL_USE_TLS="true"))["EMAIL_USE_TLS"], True)
        self.assertRefused(dict(BASE_ENV, EMAIL_USE_TLS="maybe"), "EMAIL_USE_TLS")

    def test_statement_timeout_applies_to_the_connection_options(self):
        default = load(BASE_ENV)["DATABASES"]["default"]["OPTIONS"]["options"]
        self.assertIn("cursor_tuple_fraction=1", default)
        self.assertIn("-c statement_timeout=60000", default)
        custom = load(dict(BASE_ENV, PG_STATEMENT_TIMEOUT_MS="5000"))
        self.assertIn(
            "-c statement_timeout=5000",
            custom["DATABASES"]["default"]["OPTIONS"]["options"],
        )

    def test_statement_timeout_zero_sets_none(self):
        options = load(dict(BASE_ENV, PG_STATEMENT_TIMEOUT_MS="0"))["DATABASES"][
            "default"
        ]["OPTIONS"]["options"]
        self.assertNotIn("statement_timeout", options)
        self.assertIn("cursor_tuple_fraction=1", options)

    def test_idle_in_transaction_timeout_applies_to_the_connection_options(self):
        default = load(BASE_ENV)["DATABASES"]["default"]["OPTIONS"]["options"]
        self.assertIn("-c idle_in_transaction_session_timeout=60000", default)
        custom = load(dict(BASE_ENV, PG_IDLE_IN_TRANSACTION_TIMEOUT_MS="5000"))
        self.assertIn(
            "-c idle_in_transaction_session_timeout=5000",
            custom["DATABASES"]["default"]["OPTIONS"]["options"],
        )

    def test_idle_in_transaction_timeout_zero_sets_none(self):
        options = load(dict(BASE_ENV, PG_IDLE_IN_TRANSACTION_TIMEOUT_MS="0"))[
            "DATABASES"
        ]["default"]["OPTIONS"]["options"]
        self.assertNotIn("idle_in_transaction", options)
        self.assertIn("cursor_tuple_fraction=1", options)

    def test_invalid_idle_in_transaction_timeout_is_refused(self):
        for value in ("soon", "-1"):
            with self.subTest(value=value):
                self.assertRefused(
                    dict(BASE_ENV, PG_IDLE_IN_TRANSACTION_TIMEOUT_MS=value),
                    "PG_IDLE_IN_TRANSACTION_TIMEOUT_MS",
                )

    def test_invalid_statement_timeout_is_refused(self):
        for value in ("soon", "-1"):
            with self.subTest(value=value):
                self.assertRefused(
                    dict(BASE_ENV, PG_STATEMENT_TIMEOUT_MS=value),
                    "PG_STATEMENT_TIMEOUT_MS",
                )

    def test_email_password_comes_from_its_secret_file_and_may_be_empty(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as handle:
            handle.write("relay-secret\n")
        self.addCleanup(os.unlink, handle.name)
        values = load(dict(BASE_ENV, EMAIL_HOST_PASSWORD_FILE=handle.name))
        self.assertEqual(values["EMAIL_HOST_PASSWORD"], "relay-secret")
        with tempfile.NamedTemporaryFile("w", delete=False) as empty:
            pass
        self.addCleanup(os.unlink, empty.name)
        values = load(dict(BASE_ENV, EMAIL_HOST_PASSWORD_FILE=empty.name))
        self.assertEqual(values["EMAIL_HOST_PASSWORD"], "")

    def test_logging_writes_to_the_console_only(self):
        handlers = load(BASE_ENV)["LOGGING"]["handlers"]
        self.assertTrue(handlers)
        for handler in handlers.values():
            self.assertEqual(handler["class"], "logging.StreamHandler")
            self.assertNotIn("filename", handler)


LOGGER_PROBE = textwrap.dedent("""
    import json, logging, sys
    sys.modules["manuspectrum.settings_local"] = None
    sys.modules["settings_local"] = None
    import django
    django.setup()
    names = ["django", "django.request", "django.security", "django.security.DisallowedHost"]
    classes = {}
    for name in names:
        found, logger = [], logging.getLogger(name)
        while logger:
            found += [type(h).__name__ for h in logger.handlers]
            if not logger.propagate:
                break
            logger = logger.parent
        classes[name] = found
    print(json.dumps(classes))
    """)


class LoggingTests(SimpleTestCase):
    def test_no_error_is_mailed_to_the_admins(self):
        with tempfile.TemporaryDirectory() as home:
            result = subprocess.run(
                [sys.executable, "-c", LOGGER_PROBE],
                env={
                    "PATH": os.environ["PATH"],
                    "HOME": home,
                    "PYTHONPATH": str(ROOT),
                    "DJANGO_SETTINGS_MODULE": "manuspectrum.settings_docker",
                    **BASE_ENV,
                    "ADMINS": "ops@manuspectrum.test",
                },
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
            )
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        classes = json.loads(result.stdout.strip().splitlines()[-1])
        for name, handlers in classes.items():
            with self.subTest(logger=name):
                self.assertTrue(handlers)
                self.assertNotIn("AdminEmailHandler", handlers)


COMPOSE_DIR = ROOT / "deploy" / "compose"


@skipUnless(shutil.which("docker"), "docker CLI missing")
class ComposeEnvironmentTests(SimpleTestCase):
    def test_env_example_and_compose_start_the_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "compose"
            shutil.copytree(
                COMPOSE_DIR, project, ignore=shutil.ignore_patterns("tests", ".env")
            )
            secrets = Path(tmp) / "secrets"
            secrets.mkdir()
            for name in ("pg_password", "elastic_password", "django_secret_key"):
                (secrets / name).write_text("s" * 64)
            (secrets / "email_password").write_text("")
            (Path(tmp) / "media" / "uploadedfiles").mkdir(parents=True)
            env_text = (COMPOSE_DIR / ".env.example").read_text()
            env_text = re.sub(
                r"(?m)^SECRETS_DIR=.*$", f"SECRETS_DIR={secrets}", env_text
            )
            env_text = re.sub(
                r"(?m)^MEDIA_HOST_DIR=.*$", f"MEDIA_HOST_DIR={tmp}/media", env_text
            )
            (project / ".env").write_text(env_text)
            rendered = subprocess.run(
                [
                    "docker",
                    "compose",
                    "--project-directory",
                    str(project),
                    "--env-file",
                    str(project / ".env"),
                    "-f",
                    str(project / "compose.yaml"),
                    "-f",
                    str(project / "compose.prod.yaml"),
                    "config",
                    "--format",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            environment = dict(
                line.split("=", 1)
                for line in env_text.splitlines()
                if line and not line.startswith("#") and "=" in line
            )
            environment.update(
                json.loads(rendered.stdout)["services"]["web"]["environment"]
            )
            environment = {
                key: str(value).replace("/run/secrets", str(secrets))
                for key, value in environment.items()
                if value is not None
            }
            values = load(environment)
        self.assertNotIn("error", values, values)
        self.assertEqual(values["CELERY_BROKER_URL"], "redis://redis-broker:6379/0")
