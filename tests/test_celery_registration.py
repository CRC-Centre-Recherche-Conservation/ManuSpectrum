"""Celery task registration in a plain Django process (no worker).

``app.autodiscover_tasks()`` only connects a callback to the ``import_modules``
signal, and nothing but a Celery worker emits it. A WSGI process therefore has
to import ``manuspectrum.tasks`` some other way, or the task is missing from the
registry, ``ManuspectrumConfig._check_async_indexing_config`` turns
``BIBLISSIMA_ASYNC_INDEXING`` off for the life of the process, and every
Biblissima create re-indexes Elasticsearch inside the request.

The Celery registry is process-global and the other test modules import
``manuspectrum.tasks`` for their own patching, so the assertion only means
something in a fresh interpreter: this module shells out to one.

Run:
    python manage.py test tests.test_celery_registration \\
        --settings="tests.test_settings" --noinput
"""

import os
import subprocess
import sys
import textwrap

from django.conf import settings
from django.test import SimpleTestCase

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Reads the registry through ``celery.current_app`` — the same lookup
# ``shared_task.delay()`` does — rather than importing ``manuspectrum.celery``,
# which would register the task by itself and make the assertion vacuous.
BARE_SETUP = textwrap.dedent("""
    import os

    os.environ["DJANGO_SETTINGS_MODULE"] = "tests.test_settings"

    from django.conf import settings

    # Setting an attribute on the still-lazy settings object forces it to
    # evaluate the module first, so this override survives django.setup().
    settings.BIBLISSIMA_ASYNC_INDEXING = True

    import django

    django.setup()

    from celery import current_app

    print("REGISTERED=%s" % ("manuspectrum.index_resources" in current_app.tasks))
    print("FLAG=%s" % settings.BIBLISSIMA_ASYNC_INDEXING)
    """)


class CeleryTaskRegistrationTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.child = subprocess.run(
            [sys.executable, "-c", BARE_SETUP],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )

    def test_child_process_starts_cleanly(self):
        self.assertEqual(self.child.returncode, 0, msg=self.child.stderr)

    def test_index_resources_task_is_registered(self):
        self.assertIn("REGISTERED=True", self.child.stdout, msg=self.child.stderr)

    def test_async_indexing_flag_survives_startup(self):
        self.assertIn("FLAG=True", self.child.stdout, msg=self.child.stderr)


class CeleryBeatScheduleTests(SimpleTestCase):
    def test_no_dead_notification_heartbeat(self):
        # arches.app.tasks.message returns its argument: an hourly INSERT +
        # UPDATE in django_celery_results_taskresult to log a constant string.
        self.assertNotIn("notification", settings.CELERY_BEAT_SCHEDULE)
