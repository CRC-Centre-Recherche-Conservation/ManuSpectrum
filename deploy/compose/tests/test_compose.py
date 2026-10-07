# deploy/compose/tests/test_compose.py
"""Rules of the rendered Compose stack (spec §3.2, §17.2, §17.5, §17.6).

Renders compose.yaml alone and with compose.prod.yaml through
`docker compose config` on a copy of deploy/compose with .env.example, then
checks the result. Starts nothing; needs the docker CLI with Compose v2.
"""

import json
import re
import runpy
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

COMPOSE_DIR = Path(__file__).resolve().parents[1]
DEPLOY_DIR = COMPOSE_DIR.parent
APP_SERVICES = ("web", "worker", "beat")
EXTERNAL_VOLUMES = {
    "pg_data": "ms_pg_data",
    "es_data": "ms_es_data",
    "redis_broker": "ms_redis_broker",
    "cantaloupe_cache": "ms_cantaloupe_cache",
}
MIB = 1024**2
GIB = 1024**3
PROD_LIMITS = {
    "elasticsearch": 5 * GIB,
    "postgres": 3 * GIB,
    "web": 4 * GIB,
    "worker": 2 * GIB,
    "beat": 256 * MIB,
    "cantaloupe": 1792 * MIB,
    "redis-broker": 256 * MIB,
    "redis-cache": 768 * MIB,
}


def to_bytes(value):
    match = re.fullmatch(r"(\d+)([kmg]?)b?", str(value).strip().lower())
    number, unit = int(match.group(1)), match.group(2)
    return number * {"": 1, "k": 1024, "m": MIB, "g": GIB}[unit]


def render(*files):
    """Return `docker compose config` as JSON for `files`, with .env.example values."""
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "compose"
        shutil.copytree(
            COMPOSE_DIR, project, ignore=shutil.ignore_patterns("tests", ".env")
        )
        secrets = Path(tmp) / "secrets"
        secrets.mkdir()
        for name in (
            "pg_password",
            "elastic_password",
            "django_secret_key",
            "admin_password",
        ):
            (secrets / name).write_text("x" * 64)
        (secrets / "email_password").write_text("")
        media = Path(tmp) / "media"
        (media / "uploadedfiles").mkdir(parents=True)
        env = (COMPOSE_DIR / ".env.example").read_text()
        env = re.sub(r"(?m)^SECRETS_DIR=.*$", f"SECRETS_DIR={secrets}", env)
        env = re.sub(r"(?m)^MEDIA_HOST_DIR=.*$", f"MEDIA_HOST_DIR={media}", env)
        (project / ".env").write_text(env)
        command = ["docker", "compose", "--project-directory", str(project)]
        command += ["--env-file", str(project / ".env")]
        for name in files:
            command += ["-f", str(project / name)]
        result = subprocess.run(
            command + ["config", "--format", "json"],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout), str(media)


@unittest.skipUnless(shutil.which("docker"), "docker CLI missing")
class ComposeStackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base, cls.media = render("compose.yaml")
        cls.prod, _ = render("compose.yaml", "compose.prod.yaml")
        cls.stacks = {"base": cls.base, "prod": cls.prod}

    def each_service(self):
        for label, stack in self.stacks.items():
            for name, service in stack["services"].items():
                yield label, name, service

    def test_no_service_publishes_a_port(self):
        for label, name, service in self.each_service():
            with self.subTest(stack=label, service=name):
                self.assertFalse(service.get("ports"))

    def test_every_service_restarts_logs_and_drops_privileges(self):
        for label, name, service in self.each_service():
            with self.subTest(stack=label, service=name):
                self.assertEqual(service["restart"], "unless-stopped")
                self.assertEqual(service["logging"]["driver"], "json-file")
                self.assertEqual(
                    service["logging"]["options"], {"max-size": "10m", "max-file": "5"}
                )
                self.assertIn("no-new-privileges:true", service["security_opt"])
                self.assertEqual(service["cap_drop"], ["ALL"])

    def test_every_service_has_a_healthcheck_except_beat(self):
        for label, name, service in self.each_service():
            with self.subTest(stack=label, service=name):
                if name == "beat":
                    self.assertTrue(service["healthcheck"]["disable"])
                else:
                    self.assertTrue(service["healthcheck"]["test"])

    def test_worker_healthcheck_pings_celery_not_the_web_probe(self):
        test = " ".join(self.base["services"]["worker"]["healthcheck"]["test"])
        self.assertIn("inspect ping", test)

    def test_web_and_worker_keep_metrics_on_a_tmpfs_beat_does_not(self):
        for label, stack in self.stacks.items():
            services = stack["services"]
            for name in ("web", "worker"):
                with self.subTest(stack=label, service=name):
                    self.assertEqual(
                        services[name]["environment"]["PROMETHEUS_MULTIPROC_DIR"],
                        "/run/prometheus",
                    )
                    self.assertTrue(
                        any(
                            t.startswith("/run/prometheus:")
                            and "noexec" in t
                            and "mode=1777" in t
                            for t in services[name]["tmpfs"]
                        )
                    )
            with self.subTest(stack=label, service="beat"):
                self.assertNotIn(
                    "PROMETHEUS_MULTIPROC_DIR", services["beat"]["environment"]
                )

    def test_only_the_worker_serves_its_metrics_port(self):
        for label, stack in self.stacks.items():
            services = stack["services"]
            with self.subTest(stack=label):
                self.assertEqual(
                    services["worker"]["environment"]["MS_CELERY_METRICS_PORT"], "9808"
                )
                self.assertNotIn(
                    "MS_CELERY_METRICS_PORT", services["web"]["environment"]
                )
                self.assertFalse(services["worker"].get("ports"))

    def test_worker_healthcheck_writes_no_metrics(self):
        test = " ".join(self.base["services"]["worker"]["healthcheck"]["test"])
        self.assertIn("env -u PROMETHEUS_MULTIPROC_DIR", test)

    def test_application_services_run_as_the_host_account_on_a_read_only_root(self):
        for label, name, service in self.each_service():
            if name not in APP_SERVICES:
                continue
            with self.subTest(stack=label, service=name):
                self.assertEqual(service["user"], "10001:10001")
                self.assertTrue(service["read_only"])
                self.assertTrue(any(t.startswith("/tmp:") for t in service["tmpfs"]))
                self.assertFalse(service.get("cap_add"))

    def test_dependencies_are_awaited_healthy(self):
        services = self.base["services"]
        self.assertEqual(
            {k: v["condition"] for k, v in services["web"]["depends_on"].items()},
            dict.fromkeys(
                ("postgres", "elasticsearch", "redis-broker", "redis-cache"),
                "service_healthy",
            ),
        )
        for name in ("worker", "beat"):
            self.assertEqual(
                services[name]["depends_on"]["web"]["condition"], "service_healthy"
            )

    def test_data_volumes_are_external_with_fixed_names(self):
        for label, stack in self.stacks.items():
            with self.subTest(stack=label):
                for key, name in EXTERNAL_VOLUMES.items():
                    self.assertTrue(stack["volumes"][key]["external"])
                    self.assertEqual(stack["volumes"][key]["name"], name)
                for key in ("static", "beat"):
                    self.assertFalse(stack["volumes"][key].get("external"))

    def test_media_is_the_host_directory_never_created_by_docker(self):
        for name in ("web", "worker", "cantaloupe"):
            binds = [
                v for v in self.base["services"][name]["volumes"] if v["type"] == "bind"
            ]
            with self.subTest(service=name):
                self.assertEqual(len(binds), 1)
                self.assertTrue(binds[0]["source"].startswith(self.media))
                self.assertIs(binds[0]["bind"].get("create_host_path", False), False)
        cantaloupe = [
            v
            for v in self.base["services"]["cantaloupe"]["volumes"]
            if v["type"] == "bind"
        ][0]
        self.assertEqual(cantaloupe["target"], "/imageroot")
        self.assertTrue(cantaloupe["read_only"])

    def test_source_declares_create_host_path_false_for_every_media_bind(self):
        # `docker compose config` omits a false value; the source must state it.
        source = (COMPOSE_DIR / "compose.yaml").read_text()
        self.assertEqual(source.count("create_host_path: false"), 2)
        self.assertNotIn("create_host_path: true", source)

    def test_nothing_mounts_the_docker_socket(self):
        for label, name, service in self.each_service():
            for volume in service.get("volumes", []):
                self.assertNotIn("docker.sock", str(volume.get("source", "")))

    def test_postgres_is_configured_as_arches_expects(self):
        for label, stack in self.stacks.items():
            postgres = stack["services"]["postgres"]
            with self.subTest(stack=label):
                self.assertIn("standard_conforming_strings=off", postgres["command"])
                self.assertEqual(
                    postgres["environment"]["POSTGRES_INITDB_ARGS"],
                    "--encoding=UTF8 --locale=en_US.utf8",
                )
                init = [
                    v
                    for v in postgres["volumes"]
                    if v["target"] == "/docker-entrypoint-initdb.d"
                ]
                self.assertTrue(init and init[0]["read_only"])
        sql = (COMPOSE_DIR / "postgres/init/01-template-postgis.sql").read_text()
        for statement in (
            "CREATE DATABASE template_postgis TEMPLATE template0 ENCODING 'UTF8' LOCALE 'en_US.utf8';",
            "UPDATE pg_database SET datistemplate = true WHERE datname = 'template_postgis';",
            "CREATE EXTENSION postgis;",
            'CREATE EXTENSION "uuid-ossp";',
            "GRANT ALL ON geometry_columns TO PUBLIC;",
            "GRANT ALL ON geography_columns TO PUBLIC;",
            "GRANT ALL ON spatial_ref_sys TO PUBLIC;",
        ):
            self.assertIn(statement, sql)

    def test_redis_broker_never_evicts_and_redis_cache_does(self):
        for label, stack in self.stacks.items():
            broker = " ".join(stack["services"]["redis-broker"]["command"])
            cache = " ".join(stack["services"]["redis-cache"]["command"])
            with self.subTest(stack=label):
                self.assertIn("--maxmemory-policy noeviction", broker)
                self.assertIn("--appendonly yes", broker)
                self.assertIn("--maxmemory-policy allkeys-lru", cache)
                self.assertIn("--maxmemory 512mb", cache)
                self.assertIn("--appendonly no", cache)

    def test_cantaloupe_admin_endpoint_is_disabled(self):
        environment = self.base["services"]["cantaloupe"]["environment"]
        self.assertEqual(environment["CANTALOUPE_ENDPOINT_ADMIN_ENABLED"], "false")

    def test_production_sizing(self):
        services = self.prod["services"]
        for name, limit in PROD_LIMITS.items():
            with self.subTest(service=name):
                memory = services[name]["deploy"]["resources"]["limits"]["memory"]
                self.assertEqual(to_bytes(memory), limit)
        self.assertEqual(services["web"]["environment"]["GUNICORN_WORKERS"], "5")
        self.assertEqual(services["web"]["environment"]["GUNICORN_THREADS"], "4")
        self.assertEqual(services["worker"]["environment"]["CELERY_CONCURRENCY"], "3")
        elasticsearch = services["elasticsearch"]["environment"]
        self.assertEqual(elasticsearch["ES_JAVA_OPTS"], "-Xms2g -Xmx2g")
        self.assertEqual(elasticsearch["xpack.ml.enabled"], "false")
        java = services["cantaloupe"]["environment"]["JAVA_TOOL_OPTIONS"].split()
        self.assertIn("-Xmx1g", java)
        self.assertIn("-XX:+ExitOnOutOfMemoryError", java)

    def test_production_services_never_swap(self):
        for name, limit in PROD_LIMITS.items():
            with self.subTest(service=name):
                self.assertEqual(
                    to_bytes(self.prod["services"][name]["memswap_limit"]), limit
                )

    def test_production_postgres_settings(self):
        command = self.prod["services"]["postgres"]["command"]
        settings = dict(
            item.split("=", 1) for item in command if re.match(r"^[a-z_]+=", item)
        )
        for key, value in {
            "standard_conforming_strings": "off",
            "shared_buffers": "1GB",
            "effective_cache_size": "3GB",
            "work_mem": "16MB",
            "maintenance_work_mem": "256MB",
            "autovacuum_work_mem": "128MB",
            "max_connections": "60",
        }.items():
            with self.subTest(setting=key):
                self.assertEqual(settings.get(key), value)
        self.assertNotIn("idle_in_transaction_session_timeout", " ".join(command))
        self.assertEqual(
            self.prod["services"]["postgres"]["environment"]["POSTGRES_INITDB_ARGS"],
            "--encoding=UTF8 --locale=en_US.utf8",
        )

    def test_cantaloupe_reads_the_uploaded_files_through_the_host_group(self):
        for label, stack in self.stacks.items():
            with self.subTest(stack=label):
                self.assertEqual(
                    stack["services"]["cantaloupe"]["group_add"], ["10001"]
                )

    def test_web_outlives_gunicorns_graceful_timeout(self):
        conf = runpy.run_path(str(DEPLOY_DIR / "docker" / "gunicorn.conf.py"))
        for label, stack in self.stacks.items():
            with self.subTest(stack=label):
                grace = stack["services"]["web"]["stop_grace_period"]
                self.assertEqual(grace, "5m10s")
                self.assertGreater(310, conf["graceful_timeout"])

    def test_only_web_sets_statement_and_idle_timeouts(self):
        for label, stack in self.stacks.items():
            with self.subTest(stack=label):
                services = stack["services"]
                for key in (
                    "PG_STATEMENT_TIMEOUT_MS",
                    "PG_IDLE_IN_TRANSACTION_TIMEOUT_MS",
                ):
                    self.assertEqual(services["web"]["environment"][key], "60000")
                    for name in ("worker", "beat"):
                        self.assertEqual(services[name]["environment"][key], "0")

    def test_every_declared_secret_is_made_by_make_secrets(self):
        makefile = (DEPLOY_DIR / "Makefile").read_text(encoding="utf-8")
        made = set(re.search(r"^SECRET_FILES := (.+)$", makefile, re.M)[1].split())
        for label, stack in self.stacks.items():
            with self.subTest(stack=label):
                self.assertEqual(set(stack["secrets"]), made)

    def test_smtp_password_is_an_optional_secret_file(self):
        for label, stack in self.stacks.items():
            with self.subTest(stack=label):
                self.assertIn("email_password", stack["secrets"])
                for name in APP_SERVICES:
                    service = stack["services"][name]
                    self.assertEqual(
                        service["environment"]["EMAIL_HOST_PASSWORD_FILE"],
                        "/run/secrets/email_password",
                    )
                    self.assertIn(
                        "email_password", [s["source"] for s in service["secrets"]]
                    )

    def test_cantaloupe_base_uri_is_the_public_address_plus_iiifserver(self):
        environment = self.base["services"]["cantaloupe"]["environment"]
        self.assertTrue(
            environment["CANTALOUPE_BASE_URI"].endswith("manuspectrum.test/iiifserver")
        )
        env = (COMPOSE_DIR / ".env.example").read_text()
        self.assertRegex(env, r"(?m)^PUBLIC_SERVER_ADDRESS=https://\S+/$")

    def test_third_party_images_are_pinned_by_digest(self):
        for name, service in self.base["services"].items():
            if name not in APP_SERVICES:
                with self.subTest(service=name):
                    self.assertRegex(service["image"], r"@sha256:[0-9a-f]{64}$")


class RepositoryRulesTests(unittest.TestCase):
    def test_no_make_target_removes_a_volume(self):
        makefile = (DEPLOY_DIR / "Makefile").read_text()
        for forbidden in ("down -v", "--volumes", "volume rm", "prune"):
            self.assertNotIn(forbidden, makefile)

    def test_env_example_ships_production_as_the_environment(self):
        text = (COMPOSE_DIR / ".env.example").read_text()
        self.assertRegex(text, r"(?m)^DEPLOY_ENVIRONMENT=production$")
        self.assertNotRegex(text, r"(?m)^DEPLOY_ENVIRONMENT=rehearsal")

    def test_env_example_has_no_host_specific_value(self):
        text = (COMPOSE_DIR / ".env.example").read_text()
        addresses = set(re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text)) - {
            "127.0.0.1"
        }
        self.assertEqual(addresses, set())
        self.assertIn("APP_UID=10001", text)
        self.assertIn("APP_GID=10001", text)
        self.assertNotRegex(text, r"(?i)(password|secret_key)=\S")
