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

    def test_no_preload(self):
        self.assertFalse(load().get("preload_app", False))


if __name__ == "__main__":
    unittest.main()
