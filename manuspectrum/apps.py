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

        self._check_async_indexing_config()

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
