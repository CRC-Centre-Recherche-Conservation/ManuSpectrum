"""manuspectrum.wsgi keeps the settings module the environment selects."""

import os
import subprocess
import sys
import importlib
import tempfile
import textwrap
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from tests.test_settings_docker import BASE_ENV

ROOT = Path(__file__).resolve().parent.parent

PROBE = textwrap.dedent("""
    import os, sys, types
    sys.modules["manuspectrum.settings_local"] = None
    sys.modules["settings_local"] = None
    import django.core.wsgi
    django.core.wsgi.get_wsgi_application = lambda: None
    stub = types.ModuleType("arches.app.models.system_settings")
    stub.settings = types.SimpleNamespace(update_from_db=lambda: None)
    sys.modules["arches.app.models.system_settings"] = stub
    import manuspectrum.wsgi
    print(os.environ["DJANGO_SETTINGS_MODULE"])
    """)


def settings_module_after_wsgi_import(env):
    with tempfile.TemporaryDirectory() as home:
        result = subprocess.run(
            [sys.executable, "-c", PROBE],
            env={
                "PATH": os.environ["PATH"],
                "HOME": home,
                "PYTHONPATH": str(ROOT),
                **env,
            },
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
        )
    if result.returncode != 0:
        raise AssertionError(result.stderr[-3000:])
    return result.stdout.strip().splitlines()[-1]


class WsgiSettingsModuleTests(SimpleTestCase):
    def test_the_environment_selects_the_settings_module(self):
        env = dict(BASE_ENV, DJANGO_SETTINGS_MODULE="manuspectrum.settings_docker")
        self.assertEqual(
            settings_module_after_wsgi_import(env), "manuspectrum.settings_docker"
        )

    def test_development_settings_remain_the_default(self):
        self.assertEqual(settings_module_after_wsgi_import({}), "manuspectrum.settings")


class WsgiConnectionsTests(SimpleTestCase):
    def test_import_time_connections_are_closed_after_the_settings_load(self):
        from arches.app.models.system_settings import SystemSettings
        from django.db import connections

        calls = mock.Mock()
        sys.modules.pop("manuspectrum.wsgi", None)
        self.addCleanup(sys.modules.pop, "manuspectrum.wsgi", None)
        with (
            mock.patch("django.core.wsgi.get_wsgi_application"),
            mock.patch.object(SystemSettings, "update_from_db", calls.update_from_db),
            mock.patch.object(connections, "close_all", calls.close_all),
        ):
            importlib.import_module("manuspectrum.wsgi")
        self.assertEqual(
            [call[0] for call in calls.mock_calls], ["update_from_db", "close_all"]
        )
