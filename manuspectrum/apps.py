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
        """Verify Celery task registration when BIBLISSIMA_ASYNC_INDEXING=True.

        If the task ``manuspectrum.index_resources`` is not in the Celery
        registry (e.g. because a worker was started before ``tasks.py``
        existed, or autodiscover failed), silently drop the flag so callers
        always fall back to synchronous indexing rather than queueing messages
        that no worker will ever process.

        This check runs at process startup (Django ``ready()``) so the failure
        mode is surfaced in the server logs immediately instead of silently at
        the first create request.
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
