"""The app role's rendered files match their sources: .env.example keys, units, logrotate."""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from roles import ANSIBLE_DIR

REPO = ANSIBLE_DIR.parents[1]
DEPLOY = REPO / "deploy"
ENV_EXAMPLE = DEPLOY / "compose" / ".env.example"
MAKEFILE = DEPLOY / "Makefile"
PLACEHOLDER = re.compile(r"@[A-Z_]+@")


def keys_of(path):
    return re.findall(r"^([A-Z][A-Z0-9_]*)=", path.read_text(encoding="utf-8"), re.M)


def render(out):
    subprocess.run(
        [
            str(Path(sys.executable).parent / "ansible-playbook"),
            "-i",
            "inventories/example",
            "render.yml",
            "-e",
            f"render_dir={out}",
        ],
        cwd=ANSIBLE_DIR,
        env=dict(os.environ, ANSIBLE_HOME=str(out / "home")),
        check=True,
        capture_output=True,
    )


def image_of(env_file):
    return re.search(
        r"^MANUSPECTRUM_IMAGE=(.*)$", env_file.read_text(encoding="utf-8"), re.M
    ).group(1)


class ImageInServiceTests(unittest.TestCase):
    def test_an_existing_env_keeps_its_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "env").mkdir()
            (out / "env" / ".env").write_text(
                "DEPLOY_ENVIRONMENT=production\nMANUSPECTRUM_IMAGE=registry.example/ms:2.0\n",
                encoding="utf-8",
            )
            render(out)
            self.assertEqual(image_of(out / "env" / ".env"), "registry.example/ms:2.0")

    def test_a_first_installation_takes_the_inventory_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            render(Path(tmp))
            self.assertEqual(
                image_of(Path(tmp) / "env" / ".env"),
                "registry.example/manuspectrum@sha256:" + "0" * 64,
            )


class RenderedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        render(cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_env_keys_match_env_example(self):
        self.assertEqual(keys_of(self.out / "env" / ".env"), keys_of(ENV_EXAMPLE))

    def test_release_keys_come_from_the_inventory(self):
        env = (self.out / "env" / ".env").read_text(encoding="utf-8")
        self.assertIn("\nRELEASE_CHANNEL=prod\n", env)
        self.assertIn("\nRELEASE_READY_WAIT_SECONDS=600\n", env)

    def test_the_unit_set_is_the_seventeen_files_of_the_release_flow(self):
        names = sorted(p.name for p in (self.out / "units").iterdir())
        for unit in (
            "manuspectrum-watch.service",
            "manuspectrum-watch.timer",
            "manuspectrum-update-at.service",
            "manuspectrum-update-at.timer",
            "manuspectrum-update@.service",
        ):
            self.assertIn(unit, names)
        self.assertNotIn("manuspectrum-update@.timer", names)

    def test_no_secret_key_in_env(self):
        makefile = MAKEFILE.read_text(encoding="utf-8")
        secret_files = (
            re.search(r"^SECRET_FILES := (.*)$", makefile, re.M).group(1).split()
        )
        for key in keys_of(self.out / "env" / ".env"):
            self.assertFalse(key.endswith("_PASSWORD"), key)
            self.assertNotEqual(key, "SECRET_KEY", key)
            self.assertNotIn(key.lower(), secret_files, key)

    def test_no_placeholder_left(self):
        files = list((self.out / "units").iterdir()) + list(
            (self.out / "logrotate").iterdir()
        )
        self.assertEqual(len(list((self.out / "units").iterdir())), 17)
        for path in files:
            self.assertIsNone(
                PLACEHOLDER.search(path.read_text(encoding="utf-8")), path.name
            )

    def test_rendered_files_equal_the_plain_substitution_the_shell_tests_use(self):
        for unit in sorted((self.out / "units").iterdir()):
            source = (DEPLOY / "systemd" / f"{unit.name}.in").read_text(
                encoding="utf-8"
            )
            expected = source.replace("@APP_USER@", "manuspectrum").replace(
                "@DEPLOY_DIR@", "/home/manuspectrum/manuspectrum/deploy"
            )
            self.assertEqual(unit.read_text(encoding="utf-8"), expected, unit.name)
        source = (DEPLOY / "logrotate" / "manuspectrum-nginx.in").read_text(
            encoding="utf-8"
        )
        expected = (
            source.replace("@NGINX_LOG_HOST_DIR@", "/data/manuspectrum/nginx-logs")
            .replace("@APP_USER@", "manuspectrum")
            .replace("@APP_GROUP@", "manuspectrum")
        )
        self.assertEqual(
            (self.out / "logrotate" / "manuspectrum-nginx").read_text(encoding="utf-8"),
            expected,
        )


if __name__ == "__main__":
    unittest.main()
