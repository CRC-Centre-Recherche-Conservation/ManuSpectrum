# deploy/compose/tests/test_alertmanager.py
"""Alertmanager rendering and routing of the monitoring stack (PP-6).

Runs observability/alertmanager/render.sh the way the container does (with
Alertmanager replaced by a stand-in) and checks the rendered routing, the time
windows and the inhibitions. `amtool check-config`, the route tests and the
template rendering with the pinned image run in observability/check.sh.
"""

import os
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

COMPOSE_DIR = Path(__file__).resolve().parents[1]
ALERTMANAGER_DIR = COMPOSE_DIR / "observability" / "alertmanager"
RENDER_SH = Path(
    os.environ.get("ALERTMANAGER_RENDER_SH", ALERTMANAGER_DIR / "render.sh")
)

GOOD = {
    "EMAIL_HOST": "smtp.manuspectrum.test",
    "EMAIL_PORT": "25",
    "EMAIL_USE_TLS": "false",
    "EMAIL_HOST_USER": "",
    "EMAIL_HOST_PASSWORD_FILE": "/run/secrets/email_password",
    "ALERT_EMAILS": "alerts@manuspectrum.test",
    "ALERT_EMAIL_FROM": "manuspectrum@manuspectrum.test",
    "PUBLIC_HOST": "vm.manuspectrum.test",
}
PASSWORD = "S3cretPassw0rd-do-not-print"


class RenderBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "alertmanager.yml"

    def render(self, args=(), **overrides):
        env = {
            "PATH": os.environ["PATH"],
            "ALERTMANAGER_DIR": str(ALERTMANAGER_DIR),
            "ALERTMANAGER_OUT": str(self.out),
            "ALERTMANAGER_RENDER_ONLY": "1",
            **GOOD,
            **overrides,
        }
        return subprocess.run(
            ["sh", str(RENDER_SH), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def config(self):
        return yaml.safe_load(self.out.read_text(encoding="utf-8"))


@unittest.skipIf(yaml is None, "PyYAML is required")
class RenderTests(RenderBase):
    def test_good_values_render_a_config_without_placeholders(self):
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.out.read_text(encoding="utf-8")
        self.assertNotIn("@", text.replace("@manuspectrum.test", ""))
        config = self.config()
        self.assertEqual(
            config["global"]["smtp_smarthost"], "smtp.manuspectrum.test:25"
        )
        self.assertEqual(
            config["global"]["smtp_from"], "manuspectrum@manuspectrum.test"
        )
        self.assertIs(config["global"]["smtp_require_tls"], False)
        self.assertNotIn("smtp_auth_username", config["global"])
        self.assertEqual(config["global"]["smtp_hello"], "vm.manuspectrum.test")

    def test_the_hello_name_is_the_public_host_not_the_sender_domain(self):
        result = self.render(
            PUBLIC_HOST="node1.example.test", ALERT_EMAIL_FROM="alerts@institute.test"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.config()["global"]["smtp_hello"], "node1.example.test")

    def test_a_missing_or_malformed_public_host_exits_one(self):
        for value in ("", "bad host", "a|b.test", "x&y.test", "-a.test", "a" * 254):
            with self.subTest(value=value):
                result = self.render(PUBLIC_HOST=value)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("PUBLIC_HOST", result.stderr)

    def test_every_mail_receiver_gets_every_recipient(self):
        result = self.render(
            ALERT_EMAILS=" a@manuspectrum.test , b.c@lab.manuspectrum.test,d+x@manuspectrum.test "
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        receivers = {r["name"]: r for r in self.config()["receivers"]}
        self.assertEqual(
            set(receivers),
            {"blackhole", "email-now", "email-working-hours", "heartbeat"},
        )
        for name in ("email-now", "email-working-hours", "heartbeat"):
            (email,) = receivers[name]["email_configs"]
            self.assertEqual(
                email["to"],
                "a@manuspectrum.test,b.c@lab.manuspectrum.test,d+x@manuspectrum.test",
            )
        self.assertNotIn("email_configs", receivers["blackhole"])

    def test_empty_list_exits_one_with_a_clear_message(self):
        for value in ("", "   "):
            with self.subTest(value=value):
                result = self.render(ALERT_EMAILS=value)
                self.assertEqual(result.returncode, 1)
                self.assertIn("ALERT_EMAILS", result.stderr)
                self.assertIn("empty", result.stderr)

    def test_a_malformed_list_exits_one(self):
        bad = [
            "not-an-address",
            "a@manuspectrum.test,oops",
            "a@manuspectrum.test,,b@manuspectrum.test",
            "a@manuspectrum.test,",
            ",a@manuspectrum.test",
            "a@manuspectrum",
            "a b@manuspectrum.test",
            "a@manuspectrum.test; b@manuspectrum.test",
            "a@manuspectrum.test'\nreceivers: []",
            "Name <a@manuspectrum.test>",
            "*",
        ]
        for value in bad:
            with self.subTest(value=value):
                result = self.render(ALERT_EMAILS=value)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("ALERT_EMAILS", result.stderr)
                self.assertFalse(self.out.exists())

    def test_other_malformed_values_exit_one(self):
        cases = {
            "EMAIL_HOST": ["", "smtp host", "smtp;rm", "a|b"],
            "EMAIL_PORT": ["x25", "25;", "123456"],
            "EMAIL_USE_TLS": ["yes", "True"],
            "ALERT_EMAIL_FROM": ["", "nobody", "a@b.test,c@d.test"],
        }
        for key, values in cases.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    result = self.render(**{key: value})
                    self.assertEqual(result.returncode, 1, result.stdout)
                    self.assertIn(key, result.stderr)
        with self.subTest(key="EMAIL_HOST_USER"):
            result = self.render(EMAIL_HOST_USER="us er'x")
            self.assertEqual(result.returncode, 1)
            self.assertIn("EMAIL_HOST_USER", result.stderr)

    def test_a_user_adds_the_password_file_never_the_password(self):
        secret = Path(self.tmp.name) / "email_password"
        secret.write_text(PASSWORD, encoding="utf-8")
        result = self.render(
            EMAIL_HOST_USER="relay-user",
            EMAIL_HOST_PASSWORD_FILE=str(secret),
            EMAIL_USE_TLS="true",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        config = self.config()["global"]
        self.assertEqual(config["smtp_auth_username"], "relay-user")
        self.assertEqual(config["smtp_auth_password_file"], str(secret))
        self.assertIs(config["smtp_require_tls"], True)
        for text in (
            result.stdout,
            result.stderr,
            self.out.read_text(encoding="utf-8"),
        ):
            self.assertNotIn(PASSWORD, text)

    def test_the_password_is_not_printed_when_a_value_is_refused(self):
        secret = Path(self.tmp.name) / "email_password"
        secret.write_text(PASSWORD, encoding="utf-8")
        result = self.render(
            EMAIL_HOST_USER="relay-user",
            EMAIL_HOST_PASSWORD_FILE=str(secret),
            ALERT_EMAILS="",
        )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(PASSWORD, result.stdout + result.stderr)

    def test_the_service_arguments_reach_alertmanager(self):
        result = self.render(
            args=(
                "--config.file=/tmp/alertmanager.yml",
                "--storage.path=/alertmanager",
            ),
            ALERTMANAGER_RENDER_ONLY="",
            ALERTMANAGER_BIN="/bin/echo",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "--config.file=/tmp/alertmanager.yml --storage.path=/alertmanager",
        )

    def test_a_refused_value_starts_nothing(self):
        result = self.render(
            ALERT_EMAILS="", ALERTMANAGER_RENDER_ONLY="", ALERTMANAGER_BIN="/bin/echo"
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")


class ValidateOnlyTests(RenderBase):
    def test_a_good_environment_validates_without_writing_anything(self):
        before = set(Path(self.tmp.name).iterdir())
        result = self.render(
            ALERTMANAGER_VALIDATE_ONLY="1",
            ALERTMANAGER_RENDER_ONLY="",
            ALERTMANAGER_BIN="/bin/false",
            TMPDIR=self.tmp.name,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(set(Path(self.tmp.name).iterdir()), before)
        self.assertFalse(Path(str(self.out) + ".new").exists())

    def test_a_bad_environment_is_refused_in_validate_only_mode(self):
        result = self.render(ALERTMANAGER_VALIDATE_ONLY="1", ALERT_EMAILS="oops")
        self.assertEqual(result.returncode, 1)
        self.assertIn("ALERT_EMAILS", result.stderr)

    def test_an_output_path_that_cannot_be_written_is_never_touched(self):
        result = self.render(
            ALERTMANAGER_VALIDATE_ONLY="1",
            ALERTMANAGER_OUT="/nonexistent-dir/alertmanager.yml",
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class AlertRecipientsTargetTests(unittest.TestCase):
    """`make alert-recipients`, run as the current (unprivileged) user."""

    MAKE_DIR = COMPOSE_DIR.parent

    def run_make(self, **values):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "env"
            lines = {**{k: v for k, v in GOOD.items()}, **values}
            env_file.write_text(
                "".join(f"{k}={v}\n" for k, v in lines.items()), encoding="utf-8"
            )
            marker = Path(tmp) / "compose-called"
            fake = Path(tmp) / "fake-compose"
            fake.write_text(f'#!/bin/sh\necho "$@" >{marker}\n', encoding="utf-8")
            fake.chmod(0o755)
            before = set(Path(tmp).iterdir())
            result = subprocess.run(
                [
                    "make",
                    "-C",
                    str(self.MAKE_DIR),
                    "alert-recipients",
                    f"ENV_FILE={env_file}",
                    f"COMPOSE={fake}",
                ],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=tmp,
            )
            created = set(Path(tmp).iterdir()) - before - {marker}
            return result, marker.exists(), created

    def test_good_values_recreate_alertmanager_and_write_nothing_else(self):
        result, compose_called, created = self.run_make()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(compose_called)
        self.assertEqual(created, set())

    def test_a_bad_list_stops_before_compose_is_called(self):
        result, compose_called, _ = self.run_make(ALERT_EMAILS="oops")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(compose_called)
        self.assertIn("left running unchanged", result.stderr)

    def test_a_bad_public_host_stops_before_compose_is_called(self):
        result, compose_called, _ = self.run_make(PUBLIC_HOST="bad host")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(compose_called)
        self.assertIn("PUBLIC_HOST", result.stderr)

    def test_the_recipe_never_names_dev_null_as_an_output(self):
        makefile = (self.MAKE_DIR / "Makefile").read_text(encoding="utf-8")
        recipe = makefile.split("\nalert-recipients:")[1].split("\n\n")[0]
        self.assertNotIn("/dev/null", recipe)
        self.assertNotIn("ALERTMANAGER_OUT", recipe)
        self.assertIn("ALERTMANAGER_VALIDATE_ONLY=1", recipe)


@unittest.skipIf(yaml is None, "PyYAML is required")
class RoutingTests(RenderBase):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.render().returncode, 0)
        self.config_ = self.config()
        self.routes = {r["receiver"]: r for r in self.config_["route"]["routes"]}
        self.intervals = {
            i["name"]: i["time_intervals"] for i in self.config_["time_intervals"]
        }

    def active(self, interval, when):
        """Whether `when` (an aware datetime) falls in the named interval."""
        for spec in self.intervals[interval]:
            local = when.astimezone(ZoneInfo(spec["location"]))
            first, last = (
                spec["weekdays"][0].split(":")
                if ":" in spec["weekdays"][0]
                else (spec["weekdays"][0],) * 2
            )
            names = [
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
            ]
            if not names.index(first) <= local.weekday() <= names.index(last):
                continue
            for window in spec["times"]:
                start = datetime.strptime(window["start_time"], "%H:%M").time()
                end = datetime.strptime(window["end_time"], "%H:%M").time()
                if start <= local.time() < end:
                    return True
        return False

    def route_active(self, receiver, when):
        names = self.routes[receiver].get("active_time_intervals")
        return True if not names else any(self.active(name, when) for name in names)

    def test_critical_is_mailed_at_any_hour(self):
        self.assertNotIn("active_time_intervals", self.routes["email-now"])
        self.assertNotIn("mute_time_intervals", self.routes["email-now"])
        for when in (
            datetime(
                2026, 10, 10, 3, 0, tzinfo=ZoneInfo("Europe/Paris")
            ),  # Saturday night
            datetime(2026, 10, 14, 23, 30, tzinfo=ZoneInfo("Europe/Paris")),
        ):
            self.assertTrue(self.route_active("email-now", when))

    def test_warnings_leave_only_on_weekdays_between_08_and_19_paris(self):
        paris = ZoneInfo("Europe/Paris")
        sent = [
            datetime(2026, 10, 12, 8, 0, tzinfo=paris),  # Monday
            datetime(2026, 10, 14, 12, 0, tzinfo=paris),
            datetime(2026, 10, 16, 18, 59, tzinfo=paris),  # Friday
            datetime(
                2026, 10, 14, 6, 30, tzinfo=ZoneInfo("UTC")
            ),  # 08:30 Paris, summer time
        ]
        held = [
            datetime(2026, 10, 10, 12, 0, tzinfo=paris),  # Saturday
            datetime(2026, 10, 11, 12, 0, tzinfo=paris),  # Sunday
            datetime(2026, 10, 14, 7, 59, tzinfo=paris),
            datetime(2026, 10, 14, 19, 0, tzinfo=paris),
            datetime(2026, 10, 14, 6, 30, tzinfo=paris)
            .astimezone(ZoneInfo("UTC"))
            .replace(hour=5, minute=30),  # 07:30 Paris
        ]
        for when in sent:
            self.assertTrue(self.route_active("email-working-hours", when), when)
        for when in held:
            self.assertFalse(self.route_active("email-working-hours", when), when)

    def test_the_heartbeat_window_is_monday_morning_only(self):
        paris = ZoneInfo("Europe/Paris")
        self.assertTrue(
            self.route_active("heartbeat", datetime(2026, 10, 12, 8, 0, tzinfo=paris))
        )
        self.assertTrue(
            self.route_active("heartbeat", datetime(2026, 10, 12, 8, 4, tzinfo=paris))
        )
        for when in (
            datetime(2026, 10, 12, 8, 5, tzinfo=paris),
            datetime(2026, 10, 12, 12, 0, tzinfo=paris),
            datetime(2026, 10, 13, 8, 0, tzinfo=paris),
        ):
            self.assertFalse(self.route_active("heartbeat", when), when)

    def test_the_heartbeat_flush_fits_its_window(self):
        route = self.routes["heartbeat"]

        def seconds(text):
            return int(text[:-1]) * {"s": 1, "m": 60, "h": 3600}[text[-1]]

        # At least two flushes fall in the five minutes, and repeat_interval
        # lets only the first one send.
        self.assertLessEqual(seconds(route["group_interval"]), 120)
        self.assertGreaterEqual(seconds(route["repeat_interval"]), 24 * 3600)

    def test_inhibitions(self):
        rules = self.config_["inhibit_rules"]
        reboot = [
            r for r in rules if r["source_matchers"] == ['alertname="RecentlyRebooted"']
        ]
        self.assertEqual(len(reboot), 1)
        self.assertEqual(
            reboot[0]["target_matchers"],
            ['severity=~"critical|warning"', 'alertname!="AlertTest"'],
        )
        self.assertNotIn("equal", reboot[0])
        severity = [r for r in rules if r["source_matchers"] == ['severity="critical"']]
        self.assertEqual(len(severity), 1)
        self.assertEqual(severity[0]["target_matchers"], ['severity="warning"'])
        self.assertEqual(severity[0]["equal"], ["service"])

    def test_every_mail_is_sortable_by_subject_prefix_and_category_header(self):
        receivers = {
            r["name"]: r["email_configs"][0]
            for r in self.config_["receivers"]
            if "email_configs" in r
        }
        for name in ("email-now", "email-working-hours"):
            headers = receivers[name]["headers"]
            self.assertEqual(headers["X-ManuSpectrum-Category"], "Alert")
            self.assertEqual(headers["Subject"], '{{ template "ms.subject" . }}')
        headers = receivers["heartbeat"]["headers"]
        self.assertEqual(headers["X-ManuSpectrum-Category"], "Heartbeat")
        self.assertEqual(
            headers["Subject"], "[ManuSpectrum][Heartbeat] Alerting chain OK"
        )
        self.assertTrue(headers["Subject"].isascii())

    def test_the_watchdog_route_comes_first(self):
        first = self.config_["route"]["routes"][0]
        self.assertEqual(first["receiver"], "heartbeat")
        self.assertEqual(first["matchers"], ['alertname="Watchdog"'])


class RulesAgreeWithRoutingTests(unittest.TestCase):
    @unittest.skipIf(yaml is None, "PyYAML is required")
    def test_every_rule_severity_has_a_route_decision(self):
        severities = set()
        for path in (COMPOSE_DIR / "observability" / "prometheus" / "rules").glob(
            "*.yml"
        ):
            for group in yaml.safe_load(path.read_text(encoding="utf-8"))["groups"]:
                for rule in group["rules"]:
                    severities.add(rule["labels"]["severity"])
        self.assertEqual(severities, {"critical", "warning", "info", "none"})


if __name__ == "__main__":
    unittest.main()
