"""``/metrics``: the Prometheus exposition of the process, or of every process of the
container when ``PROMETHEUS_MULTIPROC_DIR`` is set (django-prometheus' exporter).

Off unless ``settings.METRICS_ENABLED``. Internal: Prometheus reaches ``web:8000``
directly, so a request relayed by nginx (``X-Forwarded-For``) is refused; nginx
also denies the path (PP-3). Both answer a bodyless 404.
"""

from django.conf import settings
from django.http import HttpResponseNotFound
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache
from django_prometheus.exports import ExportToDjangoView


def relayed(request):
    """Whether the request came through the reverse proxy."""
    return "HTTP_X_FORWARDED_FOR" in request.META


@method_decorator(never_cache, name="dispatch")
class MetricsView(View):
    http_method_names = ["get"]

    def get(self, request):
        if not getattr(settings, "METRICS_ENABLED", False) or relayed(request):
            return HttpResponseNotFound()
        return ExportToDjangoView(request)
