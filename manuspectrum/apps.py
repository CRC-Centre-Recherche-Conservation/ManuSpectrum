from django.apps import AppConfig
from django.conf import settings


class ManuspectrumConfig(AppConfig):
    name = "manuspectrum"
    is_arches_application = True

    def ready(self):
        if settings.APP_NAME.lower() == self.name:
            from manuspectrum.utils import search_thumbnail_fetchers
