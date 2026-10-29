"""Static rules of the deployment kit that no rendered Compose file shows."""

import re
import unittest
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[2]
SIGNALLING_KILL = re.compile(
    r"\b(?:docker|dc)(?:\s+compose)?\s+kill\b.*(?:--signal|\s-s\s?[A-Z]|\s-[A-Z]{3,}\b)"
)
KIT_SUFFIXES = {".sh", ".md", ".in", ".service", ".timer", ".yaml", ".yml", ".py"}


def kit_files():
    for path in sorted(DEPLOY.rglob("*")):
        if (
            path.is_file()
            and (path.suffix in KIT_SUFFIXES or path.name == "Makefile")
            and "tests" not in path.relative_to(DEPLOY).parts
            and "rehearsal" not in path.relative_to(DEPLOY).parts
        ):
            yield path


class SignalRuleTests(unittest.TestCase):
    """`docker kill --signal` and `compose kill -s` make Docker record a manual
    stop: `unless-stopped` then leaves the container down at the next boot."""

    def test_the_kit_never_signals_a_container_through_docker_kill(self):
        found = []
        for path in kit_files():
            for number, line in enumerate(path.read_text().splitlines(), 1):
                if SIGNALLING_KILL.search(line) and "never" not in line.lower():
                    found.append(f"{path.relative_to(DEPLOY)}:{number}: {line.strip()}")
        self.assertEqual(found, [])

    def test_the_pattern_catches_the_forms_it_forbids(self):
        for line in (
            "docker kill --signal USR1 $ids",
            "dc kill -s HUP web",
            "docker compose kill -s HUP web",
            "docker kill -sHUP x",
        ):
            with self.subTest(line=line):
                self.assertTrue(SIGNALLING_KILL.search(line))
        for line in (
            "docker kill restic-container",
            "dc exec -T web sh -c 'kill -HUP 1'",
        ):
            with self.subTest(line=line):
                self.assertFalse(SIGNALLING_KILL.search(line))

    def test_the_log_rotation_reopens_inside_the_container(self):
        rule = (DEPLOY / "logrotate" / "manuspectrum-nginx.in").read_text()
        self.assertRegex(rule, r"docker exec \"\$id\" nginx -s reopen")

    def test_the_web_entrypoint_execs_gunicorn_so_pid_1_takes_the_hup(self):
        entrypoint = (DEPLOY / "docker" / "entrypoint.sh").read_text()
        self.assertIn("exec gunicorn --config /app/gunicorn.conf.py", entrypoint)
        acceptance = (DEPLOY / "ACCEPTANCE.md").read_text()
        self.assertIn("kill -HUP 1", acceptance)


class MailpitReaderTests(unittest.TestCase):
    """busybox wget (prometheus) cannot resolve service names under a host
    resolv.conf with `search .`; Mailpit is read from `web`."""

    def test_smoke_and_acceptance_read_mailpit_from_web(self):
        smoke = (DEPLOY / "compose" / "smoke.sh").read_text()
        reader = re.search(r"(?m)^mail_get\(\).*$", smoke)[0]
        self.assertIn("exec -T web curl", reader)
        self.assertNotIn("prometheus", reader)
        for name in ("ACCEPTANCE.md", "OBSERVABILITY.md"):
            text = (DEPLOY / name).read_text()
            self.assertNotRegex(text, r"exec -T prometheus wget[^\n]*mailpit", name)


class AcceptanceCommandTests(unittest.TestCase):
    def setUp(self):
        self.text = (DEPLOY / "ACCEPTANCE.md").read_text()

    def test_the_log_listing_expands_its_glob_as_root(self):
        self.assertNotIn("sudo ls -lh $(sudo docker inspect", self.text)
        self.assertIn('sudo sh -c "ls -lh $L*"', self.text)

    def test_the_secrets_aside_directory_is_removed_without_prompts(self):
        self.assertIn('rm -rf "${SECRETS_DIR:?}/aside"', self.text)
        self.assertNotIn('rm -r "${SECRETS_DIR:?}/aside"', self.text)

    def test_the_access_log_grep_does_not_match_the_bare_word_password(self):
        self.assertNotIn(r"\?|password|token=", self.text)

    def test_certs_local_precedes_init_and_monitoring_init_precedes_up(self):
        install = self.text[self.text.index("### 2.4 First installation") :]
        install = install[: install.index("\n### 2.5")]
        positions = [
            install.index("`make -C deploy certs-local`"),
            install.index("make -C deploy init` → Arches"),
            install.index("`make -C deploy monitoring-init`"),
            install.index("`make -C deploy up` → returns"),
        ]
        self.assertEqual(positions, sorted(positions))


if __name__ == "__main__":
    unittest.main()
