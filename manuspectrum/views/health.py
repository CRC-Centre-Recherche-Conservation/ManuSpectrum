from django.conf import settings
from django.http import HttpResponse, HttpResponseNotFound, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache

from manuspectrum.observability.health import readiness
from manuspectrum.observability.views import relayed


@method_decorator(never_cache, name="dispatch")
class HealthzView(View):
    """Liveness probe of the web container: the process answers HTTP.

    It checks no dependency. Arches' SetAnonymousUser middleware still reads
    the anonymous user from the database on every anonymous request, so the
    probe fails while PostgreSQL is unreachable.
    """

    def get(self, request):
        return HttpResponse("ok", content_type="text/plain")


@method_decorator(never_cache, name="dispatch")
class ReadyzView(View):
    """Readiness probe: PostgreSQL, Elasticsearch, the Celery broker, both Redis
    instances and, when ``READYZ_CANTALOUPE``, Cantaloupe (``observability/health.py``).

    200 when every component is up, else 503; JSON per component; no
    authentication. Off unless ``READYZ_ENABLED``; a request relayed by nginx gets
    a bodyless 404 (internal probe, like ``/metrics``).
    """

    http_method_names = ["get"]

    def get(self, request):
        if not getattr(settings, "READYZ_ENABLED", False) or relayed(request):
            return HttpResponseNotFound()
        report = readiness()
        return JsonResponse(report, status=200 if report["status"] == "ready" else 503)
