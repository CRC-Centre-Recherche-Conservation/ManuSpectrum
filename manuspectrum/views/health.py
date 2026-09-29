from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache


@method_decorator(never_cache, name="dispatch")
class HealthzView(View):
    """Liveness probe of the web container: the process answers HTTP.

    It checks no dependency. Arches' SetAnonymousUser middleware still reads
    the anonymous user from the database on every anonymous request, so the
    probe fails while PostgreSQL is unreachable.
    """

    def get(self, request):
        return HttpResponse("ok", content_type="text/plain")
