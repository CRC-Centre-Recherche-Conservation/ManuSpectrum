# Importing the Celery app here is what puts ``manuspectrum.tasks`` in the task
# registry of every process, not just of a Celery worker; ``apps.py`` asserts it
# at startup. Canonical Django+Celery recipe, deliberately without the
# ``try/except Exception`` ``arches/__init__.py`` wraps it in: a Celery app that
# cannot be built is a bug to see, not to degrade around.
from manuspectrum.celery import app as celery_app

__all__ = ("celery_app",)
