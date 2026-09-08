from __future__ import absolute_import, unicode_literals
import os
from celery import Celery

import platform

if platform.system().lower() == "windows":
    os.environ.setdefault("FORKED_BY_MULTIPROCESSING", "1")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "manuspectrum.settings")
app = Celery("manuspectrum")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# autodiscover_tasks() above only connects a callback to the ``import_modules``
# signal, which nothing but a Celery worker emits. Every other process needs the
# module imported explicitly to have the project tasks in its registry.
from manuspectrum import tasks  # noqa: E402,F401
