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
    "nginx": 512 * MIB,
}
PROD_LIMITS_CEILING = 17.5 * GIB


def to_bytes(value):
    match = re.fullmatch(r"(\d+)([kmg]?)b?", str(value).strip().lower())
    number, unit = int(match.group(1)), match.group(2)
    return number * {"": 1, "k": 1024, "m": MIB, "g": GIB}[unit]


def render(*files, profiles=()):
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
            "restic_password",
        ):
            (secrets / name).write_text("x" * 64)
        (secrets / "email_password").write_text("")
        media = Path(tmp) / "media"
        (media / "uploadedfiles").mkdir(parents=True)
        certs = Path(tmp) / "certs"
        for sub in ("acme-webroot", "live", "ca", "letsencrypt"):
            (certs / sub).mkdir(parents=True)
        logs = Path(tmp) / "nginx-logs"
        logs.mkdir()
        dumps = Path(tmp) / "backups"
        (dumps / "latest").mkdir(parents=True)
        (dumps / "tmp").mkdir()
        repository = Path(tmp) / "restic"
        repository.mkdir()
        metrics = Path(tmp) / "metrics"
        metrics.mkdir()
        env = (COMPOSE_DIR / ".env.example").read_text()
        env = re.sub(r"(?m)^BACKUP_DUMP_DIR=.*$", f"BACKUP_DUMP_DIR={dumps}", env)
        env = re.sub(
            r"(?m)^RESTIC_REPOSITORY_DIR=.*$",
            f"RESTIC_REPOSITORY_DIR={repository}",
            env,
        )
        env = re.sub(
            r"(?m)^METRICS_TEXTFILE_DIR=.*$", f"METRICS_TEXTFILE_DIR={metrics}", env
        )
        env = re.sub(r"(?m)^SECRETS_DIR=.*$", f"SECRETS_DIR={secrets}", env)
        env = re.sub(r"(?m)^MEDIA_HOST_DIR=.*$", f"MEDIA_HOST_DIR={media}", env)
        env = re.sub(r"(?m)^CERTS_DIR=.*$", f"CERTS_DIR={certs}", env)
        env = re.sub(r"(?m)^NGINX_LOG_HOST_DIR=.*$", f"NGINX_LOG_HOST_DIR={logs}", env)
        (project / ".env").write_text(env)
        command = ["docker", "compose", "--project-directory", str(project)]
        for profile in profiles:
            command += ["--profile", profile]
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
        cls.acme, _ = render("compose.yaml", "compose.prod.yaml", profiles=("acme",))
        cls.backup, _ = render(
            "compose.yaml", "compose.prod.yaml", profiles=("backup",)
        )

    def each_service(self):
        for label, stack in self.stacks.items():
            for name, service in stack["services"].items():
                yield label, name, service

    def test_only_nginx_publishes_ports(self):
        for label, name, service in self.each_service():
            with self.subTest(stack=label, service=name):
                if name != "nginx":
                    self.assertFalse(service.get("ports"))
                    continue
                self.assertEqual(
                    {(p["target"], p["published"]) for p in service["ports"]},
                    {(80, "80"), (443, "443")},
                )

    def test_nginx_is_hardened(self):
        for label, stack in self.stacks.items():
            nginx = stack["services"]["nginx"]
            with self.subTest(stack=label):
                self.assertTrue(nginx["read_only"])
                self.assertEqual(nginx["user"], "10001:10001")
                self.assertEqual(nginx["cap_drop"], ["ALL"])
                self.assertFalse(nginx.get("cap_add"))
                self.assertIn("no-new-privileges:true", nginx["security_opt"])
                tmpfs = {t.split(":")[0]: t for t in nginx["tmpfs"]}
                self.assertEqual(set(tmpfs), {"/tmp", "/var/cache/nginx"})
                self.assertIn("mode=1777", tmpfs["/tmp"])
                self.assertIn("size=256m", tmpfs["/var/cache/nginx"])

    def test_nginx_mounts(self):
        for label, stack in self.stacks.items():
            nginx = stack["services"]["nginx"]
            mounts = {v["target"]: v for v in nginx["volumes"]}
            with self.subTest(stack=label):
                for target in (
                    "/etc/nginx/nginx.conf",
                    "/etc/nginx/snippets",
                    "/etc/nginx/templates",
                    "/etc/nginx/errors",
                    "/etc/nginx/ffdhe2048.pem",
                    "/etc/nginx/site-errors/500.htm",
                    "/etc/nginx/certs",
                    "/var/www/acme",
                    "/srv/media",
                    "/srv/static",
                ):
                    self.assertTrue(mounts[target]["read_only"], target)
                self.assertEqual(mounts["/srv/static"]["source"], "static")
                self.assertTrue(mounts["/srv/media"]["source"].endswith("/media"))
                certs = mounts["/etc/nginx/certs"]["source"]
                self.assertTrue(certs.endswith("/certs/live"), certs)
                self.assertEqual(
                    mounts["/var/www/acme"]["source"],
                    certs[: -len("/live")] + "/acme-webroot",
                )
                logs = mounts["/var/log/manuspectrum"]
                self.assertFalse(logs.get("read_only"))
                self.assertTrue(logs["source"].endswith("nginx-logs"))
                self.assertNotIn("/etc/nginx/tests", mounts)
                self.assertEqual(len(mounts), len(nginx["volumes"]))
        source = (COMPOSE_DIR / "compose.yaml").read_text()
        nginx_source = source[
            source.index("\n  nginx:\n") : source.index("\n  certbot:\n")
        ]
        self.assertEqual(nginx_source.count("create_host_path: false"), 4)

    def test_nginx_answers_to_the_public_name_on_the_internal_network(self):
        env = (COMPOSE_DIR / ".env.example").read_text()
        host = re.search(r"(?m)^PUBLIC_SERVER_ADDRESS=https://([^/:\s]+)/$", env)[1]
        self.assertRegex(env, rf"(?m)^PUBLIC_HOST={re.escape(host)}$")
        for label, stack in self.stacks.items():
            with self.subTest(stack=label):
                networks = stack["services"]["nginx"]["networks"]
                self.assertEqual(networks["default"]["aliases"], [host])

    def test_local_ca_reaches_web_and_worker_only_as_a_read_only_certificate(self):
        for label, stack in self.stacks.items():
            for name, service in stack["services"].items():
                mounts = [
                    v
                    for v in service.get("volumes", [])
                    if v["target"] == "/run/ms-ca/ca.crt"
                ]
                with self.subTest(stack=label, service=name):
                    if name in ("web", "worker"):
                        self.assertEqual(len(mounts), 1)
                        self.assertTrue(mounts[0]["read_only"])
                        self.assertEqual(mounts[0]["source"], "/dev/null")
                    else:
                        self.assertEqual(mounts, [])
        for name in ("web", "worker", "beat"):
            for volume in self.base["services"][name].get("volumes", []):
                self.assertNotIn("privkey", str(volume.get("source", "")))
        self.assertRegex(
            (COMPOSE_DIR / ".env.example").read_text(), r"(?m)^LOCAL_CA_CERT=$"
        )

    def test_only_nginx_and_certbot_see_the_certificate_directories(self):
        for label, stack in self.stacks.items():
            for name, service in stack["services"].items():
                for v in service.get("volumes", []):
                    source = str(v.get("source", ""))
                    with self.subTest(stack=label, service=name, source=source):
                        if "/certs" not in source:
                            continue
                        self.assertIn(name, ("nginx", "certbot"))
                        self.assertNotRegex(source, r"/certs(/ca)?$")
                        self.assertNotIn("/ca", source.split("/certs", 1)[1])
                        if source.endswith("/live"):
                            self.assertEqual(
                                v["target"],
                                (
                                    "/etc/nginx/certs"
                                    if name == "nginx"
                                    else "/certs/live"
                                ),
                            )

    def test_nginx_waits_for_a_healthy_web(self):
        depends = self.base["services"]["nginx"]["depends_on"]
        self.assertEqual(depends["web"]["condition"], "service_healthy")
        self.assertEqual(depends["cantaloupe"]["condition"], "service_started")

    def test_nginx_renders_only_its_two_variables(self):
        nginx = self.base["services"]["nginx"]
        environment = nginx["environment"]
        self.assertEqual(environment["NGINX_ENVSUBST_OUTPUT_DIR"], "/tmp")
        # `config` renders the Compose escape `$$` as is; the container sees one `$`.
        self.assertEqual(
            environment["NGINX_ENVSUBST_FILTER"], "^(DOMAIN_NAMES|HSTS_MAX_AGE)$$"
        )
        self.assertEqual(environment["DOMAIN_NAMES"], "manuspectrum.test")
        self.assertEqual(environment["HSTS_MAX_AGE"], "3600")
        self.assertNotIn("NGINX_ENVSUBST_TEMPLATE_DIR", environment)
        self.assertIn(
            "127.0.0.1:8081/nginx-health", " ".join(nginx["healthcheck"]["test"])
        )

    def test_cantaloupe_writes_no_access_log(self):
        environment = self.base["services"]["cantaloupe"]["environment"]
        self.assertEqual(
            environment["CANTALOUPE_LOG_ACCESS_CONSOLEAPPENDER_ENABLED"], "false"
        )

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
                v
                for v in self.base["services"][name]["volumes"]
                if v["type"] == "bind" and v["target"] != "/run/ms-ca/ca.crt"
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
        self.assertEqual(source.count("create_host_path: false"), 2 + 4 + 4 + 1 + 5)
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

    def test_production_limits_stay_within_the_budget(self):
        self.assertLessEqual(sum(PROD_LIMITS.values()), PROD_LIMITS_CEILING)
        self.assertEqual(sum(PROD_LIMITS.values()), PROD_LIMITS_CEILING)

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
        self.assertEqual(set(self.backup["secrets"]), made)
        for label, stack in self.stacks.items():
            with self.subTest(stack=label):
                self.assertEqual(set(stack["secrets"]), made - {"restic_password"})

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

    def test_certbot_runs_only_under_the_acme_profile(self):
        self.assertNotIn("certbot", self.base["services"])
        self.assertNotIn("certbot", self.prod["services"])
        self.assertIn("certbot", self.acme["services"])

    def test_certbot_is_hardened_and_publishes_nothing(self):
        certbot = self.acme["services"]["certbot"]
        self.assertEqual(certbot["user"], "10001:10001")
        self.assertTrue(certbot["read_only"])
        self.assertEqual(certbot["cap_drop"], ["ALL"])
        self.assertFalse(certbot.get("cap_add"))
        self.assertIn("no-new-privileges:true", certbot["security_opt"])
        self.assertFalse(certbot.get("ports"))
        self.assertEqual(certbot["restart"], "no")
        self.assertEqual([t.split(":")[0] for t in certbot["tmpfs"]], ["/tmp"])

    def test_certbot_mounts_three_certificate_directories_and_the_hook_read_only(self):
        certbot = self.acme["services"]["certbot"]
        mounts = {v["target"]: v for v in certbot["volumes"]}
        self.assertEqual(
            set(mounts),
            {
                "/certs/live",
                "/certs/letsencrypt",
                "/certs/acme-webroot",
                "/hooks/deploy-hook.sh",
            },
        )
        for name in ("live", "letsencrypt", "acme-webroot"):
            self.assertFalse(mounts[f"/certs/{name}"].get("read_only"))
            self.assertTrue(
                mounts[f"/certs/{name}"]["source"].endswith(f"/certs/{name}")
            )
        self.assertTrue(mounts["/hooks/deploy-hook.sh"]["read_only"])
        self.assertIn("--config-dir=/certs/letsencrypt", certbot["entrypoint"])
        self.assertFalse(certbot.get("secrets"))

    def test_third_party_images_are_pinned_by_digest(self):
        for label, stack in (("acme", self.acme), ("backup", self.backup)):
            for name, service in stack["services"].items():
                if name not in APP_SERVICES:
                    with self.subTest(profile=label, service=name):
                        self.assertRegex(service["image"], r"@sha256:[0-9a-f]{64}$")

    def test_restic_runs_only_under_the_backup_profile(self):
        self.assertNotIn("restic", self.base["services"])
        self.assertNotIn("restic", self.prod["services"])
        self.assertNotIn("restic", self.acme["services"])
        self.assertIn("restic", self.backup["services"])

    def test_restic_is_hardened_and_offline(self):
        restic = self.backup["services"]["restic"]
        self.assertEqual(restic["network_mode"], "none")
        self.assertTrue(restic["read_only"])
        self.assertEqual(restic["user"], "10001:10001")
        self.assertEqual(restic["cap_drop"], ["ALL"])
        self.assertFalse(restic.get("cap_add"))
        self.assertIn("no-new-privileges:true", restic["security_opt"])
        self.assertFalse(restic.get("ports"))
        self.assertEqual(restic["restart"], "no")
        self.assertTrue(restic["healthcheck"]["disable"])

    def test_restic_reads_its_sources_read_only_and_writes_only_the_repository(self):
        restic = self.backup["services"]["restic"]
        mounts = {v["target"]: v for v in restic["volumes"]}
        self.assertEqual(
            set(mounts),
            {"/repo", "/restic-tmp", "/backup/db", "/backup/media", "/backup/secrets"},
        )
        self.assertFalse(mounts["/repo"].get("read_only"))
        self.assertFalse(mounts["/restic-tmp"].get("read_only"))
        for target in ("/backup/db", "/backup/media", "/backup/secrets"):
            with self.subTest(target=target):
                self.assertTrue(mounts[target]["read_only"])
        for target, mount in mounts.items():
            with self.subTest(bind=target):
                self.assertEqual(mount["type"], "bind")
                self.assertFalse(mount.get("bind", {}).get("create_host_path", False))
        self.assertTrue(mounts["/backup/db"]["source"].endswith("/backups/latest"))
        self.assertTrue(mounts["/backup/media"]["source"].endswith("/media"))
        self.assertTrue(mounts["/restic-tmp"]["source"].endswith("/backups/tmp"))
        self.assertEqual(
            [t.split(":")[0] for t in restic["tmpfs"]],
            ["/tmp"],
        )

    def test_restic_temporary_packs_go_to_disk_not_to_the_small_tmpfs(self):
        restic = self.backup["services"]["restic"]
        self.assertEqual(restic["environment"]["TMPDIR"], "/restic-tmp")
        size = re.search(r"size=(\w+)", restic["tmpfs"][0])[1]
        self.assertLessEqual(to_bytes(size), 16 * 1024 * 1024)

    def test_restic_password_is_a_file_secret_of_restic_only(self):
        restic = self.backup["services"]["restic"]
        environment = restic["environment"]
        self.assertEqual(
            environment["RESTIC_PASSWORD_FILE"], "/run/secrets/restic_password"
        )
        self.assertNotIn("RESTIC_PASSWORD", environment)
        self.assertEqual(environment["RESTIC_HOST"], "manuspectrum")
        self.assertEqual([s["source"] for s in restic["secrets"]], ["restic_password"])
        for name, service in self.backup["services"].items():
            if name != "restic":
                with self.subTest(service=name):
                    self.assertNotIn(
                        "restic_password",
                        [s["source"] for s in service.get("secrets", [])],
                    )

    def test_restic_has_its_own_production_limit(self):
        restic = self.backup["services"]["restic"]
        self.assertEqual(
            to_bytes(restic["deploy"]["resources"]["limits"]["memory"]), GIB
        )
        self.assertEqual(to_bytes(restic["memswap_limit"]), GIB)
        self.assertNotIn("restic", PROD_LIMITS)
        steady = sum(
            to_bytes(s["deploy"]["resources"]["limits"]["memory"])
            for n, s in self.prod["services"].items()
        )
        self.assertEqual(steady, sum(PROD_LIMITS.values()))

    def test_env_example_declares_the_backup_paths(self):
        text = (COMPOSE_DIR / ".env.example").read_text()
        for name in (
            "BACKUP_DUMP_DIR",
            "RESTIC_REPOSITORY_DIR",
            "METRICS_TEXTFILE_DIR",
        ):
            with self.subTest(name=name):
                self.assertRegex(text, rf"(?m)^{name}=/[^\s]+$")


class RepositoryRulesTests(unittest.TestCase):
    def test_no_make_target_removes_a_volume(self):
        makefile = (DEPLOY_DIR / "Makefile").read_text()
        for forbidden in ("down -v", "--volumes", "volume rm", "prune"):
            self.assertNotIn(forbidden, makefile)

    def test_makefile_drives_nginx_and_the_local_certificates(self):
        makefile = (DEPLOY_DIR / "Makefile").read_text()
        self.assertRegex(makefile, r"(?m)^nginx-test:.*\n\t.*exec nginx nginx -t$")
        self.assertRegex(makefile, r"(?m)^\t.*exec nginx nginx -s reload$")
        self.assertIn("certs/make-local-ca.sh", makefile)
        self.assertRegex(makefile, r"(?m)^certs-local:")

    def test_secret_targets_pass_the_directory_and_the_names_to_their_scripts(self):
        makefile = (DEPLOY_DIR / "Makefile").read_text(encoding="utf-8")
        phony = re.search(r"(?m)^\.PHONY:(.*)$", makefile)[1].split()
        for target, script in (
            ("secret-set", "secret-set.sh"),
            ("secrets-check", "secrets-check.sh"),
        ):
            with self.subTest(target=target):
                self.assertIn(target, phony)
                self.assertRegex(makefile, rf"(?m)^{target}:.*## \S")
                recipe = re.search(rf"(?ms)^{target}:.*?\n(.*?)(?:\n\n|\Z)", makefile)[
                    1
                ]
                self.assertIn(script, recipe)
                self.assertIn("$(SECRETS_DIR)", recipe)
                self.assertIn("$(SECRET_FILES)", recipe)
                self.assertTrue((DEPLOY_DIR / "scripts" / script).is_file())

    def test_backup_targets_pass_the_metrics_directory(self):
        makefile = (DEPLOY_DIR / "Makefile").read_text(encoding="utf-8")
        phony = re.search(r"(?m)^\.PHONY:(.*)$", makefile)[1].split()
        for target, option in (
            ("backup-init", "--init"),
            ("backup", "--tag"),
            ("restic", "--restic"),
        ):
            with self.subTest(target=target):
                self.assertIn(target, phony)
                self.assertRegex(makefile, rf"(?m)^{target}:.*## \S")
                recipe = re.search(rf"(?ms)^{target}:.*?\n(.*?)(?:\n\n|\Z)", makefile)[
                    1
                ]
                self.assertIn("$(BACKUP_ENV)", recipe)
                self.assertIn(
                    f"scripts/backup.sh {option}",
                    recipe.replace("$(SCRIPTS_DIR)/", "scripts/"),
                )
        env = re.search(r"(?m)^BACKUP_ENV =(.*)$", makefile)[1]
        self.assertIn("METRICS_TEXTFILE_DIR=", env)
        self.assertIn("$(call envval,METRICS_TEXTFILE_DIR)", env)
        self.assertTrue((DEPLOY_DIR / "scripts" / "backup.sh").is_file())

    def test_restore_test_target_passes_the_metrics_directory_and_an_optional_snapshot(
        self,
    ):
        makefile = (DEPLOY_DIR / "Makefile").read_text(encoding="utf-8")
        phony = re.search(r"(?m)^\.PHONY:(.*)$", makefile)[1].split()
        self.assertIn("restore-test", phony)
        self.assertRegex(makefile, r"(?m)^restore-test:.*## \S")
        recipe = re.search(r"(?ms)^restore-test:.*?\n(.*?)(?:\n\n|\Z)", makefile)[1]
        self.assertIn("$(BACKUP_ENV)", recipe)
        self.assertIn(
            "scripts/restore-test.sh", recipe.replace("$(SCRIPTS_DIR)/", "scripts/")
        )
        self.assertRegex(
            recipe,
            r"\$\(if \$\(RESTIC_SNAPSHOT\), --snapshot '\$\(RESTIC_SNAPSHOT\)'\)",
        )
        self.assertTrue((DEPLOY_DIR / "scripts" / "restore-test.sh").is_file())

    def test_restore_targets_forward_their_variables(self):
        makefile = (DEPLOY_DIR / "Makefile").read_text(encoding="utf-8")
        phony = re.search(r"(?m)^\.PHONY:(.*)$", makefile)[1].split()
        for target, script, variables in (
            (
                "restore",
                "restore.sh",
                ("CONFIRM", "ERASURES_CHECKED", "RESTIC_SNAPSHOT", "ASIDE"),
            ),
            (
                "restore-files",
                "restore-files.sh",
                ("RESTIC_SNAPSHOT", "INCLUDE", "TARGET"),
            ),
        ):
            with self.subTest(target=target):
                self.assertIn(target, phony)
                self.assertRegex(makefile, rf"(?m)^{target}:.*## \S")
                recipe = re.search(rf"(?ms)^{target}:.*?\n(.*?)(?:\n\n|\Z)", makefile)[
                    1
                ]
                self.assertIn(
                    f"scripts/{script}", recipe.replace("$(SCRIPTS_DIR)/", "scripts/")
                )
                for variable in ("COMPOSE", "ENV_FILE") + variables:
                    self.assertIn(f"{variable}='$({variable})'", recipe)
                self.assertTrue((DEPLOY_DIR / "scripts" / script).is_file())

    def test_secret_set_needs_a_name_and_forwards_force_only_on_yes(self):
        makefile = (DEPLOY_DIR / "Makefile").read_text(encoding="utf-8")
        recipe = re.search(r"(?ms)^secret-set:.*?\n(.*?)(?:\n\n|\Z)", makefile)[1]
        self.assertIn("$(NAME)", recipe)
        self.assertRegex(recipe, r"\$\(if \$\(filter yes,\$\(FORCE\)\),--force\)")

    def test_every_secret_is_documented(self):
        makefile = (DEPLOY_DIR / "Makefile").read_text(encoding="utf-8")
        names = re.search(r"^SECRET_FILES := (.+)$", makefile, re.M)[1].split()
        text = (DEPLOY_DIR / "SECRETS.md").read_text(encoding="utf-8")
        for name in names:
            with self.subTest(secret=name):
                self.assertRegex(text, rf"(?m)^\| `{name}` \|")

    def test_backup_doc_covers_every_target(self):
        doc = (DEPLOY_DIR / "BACKUP.md").read_text(encoding="utf-8")
        readme = (DEPLOY_DIR / "README.md").read_text(encoding="utf-8")
        for target in (
            "backup-init",
            "backup",
            "restore-test",
            "restore",
            "restore-files",
            "restic",
        ):
            with self.subTest(target=target):
                self.assertIn(f"make -C deploy {target}", doc)
                self.assertRegex(readme, rf"(?m)^\| `{target}` \|")

    def test_backup_doc_states_the_retention_of_the_script(self):
        lib = (DEPLOY_DIR / "scripts" / "lib-backup.sh").read_text(encoding="utf-8")
        kept = [
            re.search(rf"(?m)^RETENTION_KEEP_{period}=(\d+)$", lib)[1]
            for period in ("DAILY", "WEEKLY", "MONTHLY")
        ]
        doc = (DEPLOY_DIR / "BACKUP.md").read_text(encoding="utf-8")
        self.assertIn("{} daily, {} weekly, {} monthly".format(*kept), doc)

    def test_scripts_point_to_a_heading_of_the_backup_doc(self):
        doc = (DEPLOY_DIR / "BACKUP.md").read_text(encoding="utf-8")
        self.assertRegex(doc, r"(?m)^## Personal data$")
        restore = (DEPLOY_DIR / "scripts" / "restore.sh").read_text(encoding="utf-8")
        self.assertIn("deploy/BACKUP.md", restore)

    def test_cert_renew_reloads_on_a_change_and_exits_with_certbots_status(self):
        cases = [
            ("changed, certbot fails", "echo new > $$CERT; exit 3", True, False),
            ("changed, certbot succeeds", "echo new > $$CERT", True, True),
            ("unchanged, certbot succeeds", "true", False, True),
            ("unchanged, certbot fails", "exit 3", False, False),
        ]
        for label, certbot, reloaded, succeeds in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as tmp:
                tmp = Path(tmp)
                (tmp / "live").mkdir()
                cert = tmp / "live" / "fullchain.pem"
                cert.write_text("old\n")
                env = (COMPOSE_DIR / ".env.example").read_text()
                env = re.sub(r"(?m)^CERT_MODE=.*$", "CERT_MODE=acme", env)
                env = re.sub(r"(?m)^CERTS_DIR=.*$", f"CERTS_DIR={tmp}", env)
                (tmp / "env").write_text(env)
                fake = tmp / "compose"
                fake.write_text(f'#!/bin/sh\necho "$@" >> {tmp}/calls\n')
                fake.chmod(0o755)
                result = subprocess.run(
                    [
                        "make",
                        "-C",
                        str(DEPLOY_DIR),
                        "cert-renew",
                        f"ENV_FILE={tmp}/env",
                        f"COMPOSE={fake}",
                        f"CERTBOT=env CERT={cert} sh -c '{certbot}'",
                    ],
                    capture_output=True,
                    text=True,
                )
                calls = (tmp / "calls").read_text() if (tmp / "calls").exists() else ""
                self.assertEqual("nginx -s reload" in calls, reloaded, result.stderr)
                self.assertEqual(result.returncode == 0, succeeds, result.stderr)

    def test_acme_targets_refuse_outside_acme_mode_or_without_a_contact(self):
        makefile = (DEPLOY_DIR / "Makefile").read_text()
        self.assertRegex(makefile, r"(?m)^cert-init:")
        self.assertRegex(makefile, r"(?m)^cert-renew:")
        env = (COMPOSE_DIR / ".env.example").read_text()
        cases = {
            "cert-init": [
                ("CERT_MODE=local", "ACME_EMAIL=ops@manuspectrum.test", "not acme"),
                ("CERT_MODE=acme", "ACME_EMAIL=", "set ACME_EMAIL"),
            ],
            "cert-renew": [("CERT_MODE=provided", "ACME_EMAIL=", "not acme")],
        }
        with tempfile.TemporaryDirectory() as tmp:
            for target, variants in cases.items():
                for mode, email, message in variants:
                    text = re.sub(r"(?m)^CERT_MODE=.*$", mode, env)
                    text = re.sub(r"(?m)^ACME_EMAIL=.*$", email, text)
                    path = Path(tmp) / "env"
                    path.write_text(text)
                    with self.subTest(target=target, mode=mode, email=email):
                        result = subprocess.run(
                            ["make", "-C", str(DEPLOY_DIR), target, f"ENV_FILE={path}"],
                            capture_output=True,
                            text=True,
                        )
                        self.assertEqual(result.returncode, 2)
                        self.assertIn(message, result.stderr)

    def test_acme_server_defaults_to_the_staging_directory(self):
        env = (COMPOSE_DIR / ".env.example").read_text()
        self.assertRegex(
            env,
            r"(?m)^ACME_SERVER=https://acme-staging-v02\.api\.letsencrypt\.org/directory$",
        )

    def test_renewal_units_run_the_make_target_twice_a_day(self):
        service = (
            DEPLOY_DIR / "systemd/manuspectrum-cert-renew.service.in"
        ).read_text()
        timer = (DEPLOY_DIR / "systemd/manuspectrum-cert-renew.timer.in").read_text()
        self.assertIn("ExecStart=/usr/bin/make -C @DEPLOY_DIR@ cert-renew", service)
        self.assertIn("OnCalendar=*-*-* 00,12:00", timer)
        self.assertIn("RandomizedDelaySec=1h", timer)
        self.assertIn("Persistent=true", timer)

    def test_backup_units_run_the_make_targets(self):
        def unit(name):
            return (DEPLOY_DIR / f"systemd/manuspectrum-{name}.in").read_text()

        def timeout(text):
            value = re.search(r"(?m)^TimeoutStartSec=(\S+)$", text)[1]
            match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)min)?", value)
            return int(match[1] or 0) * 60 + int(match[2] or 0)

        for name, target, calendar, limit in (
            ("backup", "backup TAG=nightly", "OnCalendar=*-*-* 02:00", 150),
            ("restore-test", "restore-test", "OnCalendar=Sun *-*-* 05:30", 120),
        ):
            with self.subTest(unit=name):
                service = unit(f"{name}.service")
                timer = unit(f"{name}.timer")
                self.assertRegex(
                    service,
                    rf"(?m)^ExecStart=/usr/bin/make -C @DEPLOY_DIR@ {target}$",
                )
                self.assertRegex(service, r"(?m)^Type=oneshot$")
                self.assertRegex(service, r"(?m)^User=@APP_USER@$")
                self.assertRegex(service, r"(?m)^Wants=network-online\.target$")
                self.assertRegex(
                    service,
                    r"(?m)^After=docker\.service network-online\.target remote-fs\.target$",
                )
                self.assertNotIn("RequiresMountsFor", service)
                self.assertEqual(timeout(service), limit)
                self.assertIn(calendar + "\n", timer)
                self.assertIn("Persistent=true", timer)
                self.assertNotIn("RandomizedDelaySec", timer)
                self.assertIn("WantedBy=timers.target", timer)
        # The unattended reboot is at 04:50: the backup must have stopped.
        self.assertLess(2 * 60 + timeout(unit("backup.service")), 4 * 60 + 50)

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
        for name in ("CERTS_DIR", "NGINX_LOG_HOST_DIR"):
            self.assertRegex(text, rf"(?m)^{name}=/data/manuspectrum/\S+$")
        self.assertRegex(text, r"(?m)^CERT_MODE=local$")
        self.assertRegex(text, r"(?m)^HSTS_MAX_AGE=3600$")
        self.assertRegex(text, r"(?m)^ACME_EMAIL=$")
        self.assertNotRegex(text, r"(?i)(password|secret_key)=\S")
