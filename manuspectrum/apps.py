import logging

from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger(__name__)


class ManuspectrumConfig(AppConfig):
    name = "manuspectrum"
    is_arches_application = True

    def ready(self):
        if settings.APP_NAME.lower() == self.name:
            from manuspectrum.utils import search_thumbnail_fetchers

        from manuspectrum import checks  # noqa: F401  (registers system checks)

        self._check_async_indexing_config()
        self._check_contact_email_config()

    def _check_async_indexing_config(self):
        """Turn BIBLISSIMA_ASYNC_INDEXING off in this process when the task is missing.

        ``manuspectrum/__init__.py`` imports the Celery app, so the tasks module
        is loaded well before ``ready()`` runs; what is left to catch here is
        ``manuspectrum.index_resources`` being renamed or removed. Nothing is
        written to disk — the flag is cleared in memory, for this process only,
        so callers index synchronously instead of queueing messages no worker
        would consume.

        Whether a *worker* is alive is a distributed fact this cannot see; the
        ``.delay()`` try/except in ``_defer_indexing`` covers that.
        """
        if not getattr(settings, "BIBLISSIMA_ASYNC_INDEXING", False):
            return

        try:
            from manuspectrum.celery import app as celery_app  # noqa

            if "manuspectrum.index_resources" not in celery_app.tasks:
                logger.error(
                    "BIBLISSIMA_ASYNC_INDEXING=True but task "
                    "'manuspectrum.index_resources' is not registered. "
                    "Falling back to synchronous indexing."
                )
                settings.BIBLISSIMA_ASYNC_INDEXING = False
        except Exception as exc:
            logger.error(
                "Could not verify Celery task registry: %s. "
                "Disabling async indexing.",
                exc,
            )
            settings.BIBLISSIMA_ASYNC_INDEXING = False

    def _check_contact_email_config(self):
        """Surface a placeholder contact address in server logs at startup.

        The system check in ``manuspectrum.checks`` already turns this into a
        hard Error for management commands (so ``migrate`` refuses to run on a
        misconfigured prod). Gunicorn/Celery workers never run system checks,
        so this logs loudly at process startup too — without taking the whole
        site down over a contact address.
        """
        from manuspectrum import checks

        email = checks.effective_contact_email()
        if not settings.DEBUG and checks.is_placeholder_email(email):
            logger.error(
                "Public contact address is still the placeholder %r "
                "(CONTACT_EMAIL / DEFAULT_FROM_EMAIL). The About > Contact "
                "page is publishing a dead mailto: link — set a real address "
                "in settings_local.py.",
                email,
            )
