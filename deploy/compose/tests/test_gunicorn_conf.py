"""Rules of deploy/docker/gunicorn.conf.py, executed as a module."""

import os
import runpy
import unittest
from pathlib import Path
from unittest import mock

CONF = Path(__file__).resolve().parents[2] / "docker" / "gunicorn.conf.py"


def load(**env):
    clean = {k: v for k, v in os.environ.items() if not k.startswith("GUNICORN_")}
    clean.update(env)
    with mock.patch.dict(os.environ, clean, clear=True):
        return runpy.run_path(str(CONF))


class GunicornConfTests(unittest.TestCase):
    def test_worker_class_is_gthread(self):
        self.assertEqual(load()["worker_class"], "gthread")

    def test_defaults(self):
        conf = load()
        self.assertEqual(conf["threads"], 4)
        self.assertEqual(conf["workers"], 2)

    def test_threads_and_workers_come_from_the_environment(self):
        conf = load(GUNICORN_THREADS="6", GUNICORN_WORKERS="3")
        self.assertEqual(conf["threads"], 6)
        self.assertEqual(conf["workers"], 3)

    def test_graceful_timeout_lets_long_downloads_finish(self):
        conf = load()
        self.assertEqual(conf["graceful_timeout"], 300)
        self.assertEqual(conf["max_requests"], 1000)
        self.assertEqual(conf["max_requests_jitter"], 100)

    def test_timeout_defaults_above_graceful_timeout(self):
        conf = load()
        self.assertEqual(conf["timeout"], 330)
        self.assertGreaterEqual(conf["timeout"], conf["graceful_timeout"])

    def test_timeout_comes_from_the_environment(self):
        conf = load(GUNICORN_TIMEOUT="400", GUNICORN_GRACEFUL_TIMEOUT="60")
        self.assertEqual(conf["timeout"], 400)

    def test_timeout_below_graceful_timeout_is_refused(self):
        with self.assertRaises(ValueError):
            load(GUNICORN_TIMEOUT="100")
        with self.assertRaises(ValueError):
            load(GUNICORN_TIMEOUT="60", GUNICORN_GRACEFUL_TIMEOUT="61")

    def test_graceful_timeout_comes_from_the_environment(self):
        self.assertEqual(load(GUNICORN_GRACEFUL_TIMEOUT="60")["graceful_timeout"], 60)

    def test_no_preload(self):
        self.assertFalse(load().get("preload_app", False))


if __name__ == "__main__":
    unittest.main()
